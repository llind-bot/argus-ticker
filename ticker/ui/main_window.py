"""Main window: the watchlist table, toolbar, status bar and tray alerts."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QIcon, QKeySequence, QPainter,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QMainWindow, QMenu, QMessageBox, QProgressDialog, QPushButton,
                               QStackedWidget, QSystemTrayIcon, QTableView, QToolBar, QVBoxLayout, QWidget)

from .. import __version__, market, selfupdate, settings, transfer, updates
from ..db import DuplicateEntry, Store, default_path
from ..format import AlertTracker
from ..quotes import QuoteService
from . import theme
from .alerts import AlertsWindow
from .dialogs import EntryDialog, SettingsDialog
from .live_views import CardsView, ListView, scrolling
from .overlays import FloatingWidget, TickerStrip
from .state import LiveState
from .table_model import WatchlistModel

MAIN_VIEWS = ("cards", "list", "edit")
VIEW_LABELS = {"cards": "Cards", "list": "List", "edit": "Edit", "widget": "Floating widget",
               "strip": "Ticker strip"}

_SEG_CSS = """
QPushButton { font-size: 12px; border: 0; border-radius: 6px; padding: 6px 14px; background: transparent;
              color: #8B98A5; }
QPushButton:checked { background: #243041; color: #E6EDF3; }
QPushButton:hover:!checked { color: #E6EDF3; }
"""
_BAR_CSS = "#topbar { background: #0B0F14; border-bottom: 1px solid #1C2430; }"


def app_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(15, 23, 42))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    p.setPen(QColor(34, 197, 94))
    pen = p.pen()
    pen.setWidth(6)
    p.setPen(pen)
    p.drawPolyline([QPoint(12, 44), QPoint(26, 30), QPoint(36, 38), QPoint(52, 18)])
    p.end()
    return QIcon(pix)


class _UpdateChecker(QObject):
    done = Signal(object, bool)                  # UpdateInfo | None, asked by the user

    def start(self, manual: bool) -> None:
        threading.Thread(target=lambda: self.done.emit(updates.check(), manual), daemon=True).start()


class _Installer(QObject):
    """Runs selfupdate.install on a thread; reports progress and the result to the GUI."""
    progress = Signal(int, int)
    done = Signal(object)                        # None on success, else the error text

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.cancelled = False

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        def report(done: int, total: int) -> bool:
            self.progress.emit(done, total)
            return not self.cancelled
        try:
            selfupdate.install(self.info.exe_url, report, self.info.sha256, self.info.sha_url)
            self.done.emit(None)
        except Exception as e:                   # noqa: BLE001 — shown to the user
            self.done.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.prefs = settings.load_prefs()
        self.alerts = AlertTracker()
        self.alerts_win = None
        self.setWindowTitle(f"Argus Ticker {__version__}")
        self.market = market.estimate()
        self.setWindowIcon(app_icon())
        self.resize(820, 420)

        self.state = LiveState(self)
        self.state.scheme = self.prefs.scheme
        self.model = WatchlistModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _: self.edit_entry())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

        self.cards = CardsView(self.state)
        self.list_view = ListView(self.state)
        for v in (self.cards, self.list_view):
            v.activated.connect(self._edit_by_id)
        edit_page = QWidget()
        edit_lay = QVBoxLayout(edit_page)
        edit_lay.setContentsMargins(0, 0, 0, 0)
        edit_lay.setSpacing(0)
        edit_lay.addWidget(self._build_actions())
        edit_lay.addWidget(self.table)
        self.stack = QStackedWidget()
        self.stack.addWidget(scrolling(self.cards))
        self.stack.addWidget(scrolling(self.list_view))
        self.stack.addWidget(edit_page)
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_topbar())
        lay.addWidget(self.stack)
        self.setCentralWidget(central)

        self.widget_win = FloatingWidget(self.state)
        self.strip_win = TickerStrip(self.state)
        for o in (self.widget_win, self.strip_win):
            o.open_main.connect(self._show_main)
            o.switch_to.connect(self.set_view)
        self._build_menus()
        self.status_labels = {name: QLabel(f"{name}: idle") for name in ("Alpaca", "Coinbase", "Metals")}
        for lbl in self.status_labels.values():
            self.statusBar().addPermanentWidget(lbl)

        self.tray = QSystemTrayIcon(app_icon(), self) if QSystemTrayIcon.isSystemTrayAvailable() else None
        if self.tray:
            self.tray.setToolTip("Argus Ticker")
            self.tray.activated.connect(self._tray_activated)
            self.tray.messageClicked.connect(self.show_alerts)
            menu = QMenu()
            menu.addAction("Open watchlist", self._show_main)
            menu.addAction("Alerts…", self.show_alerts)
            menu.addSeparator()
            for v in ("cards", "list", "widget", "strip"):
                menu.addAction(VIEW_LABELS[v], lambda v=v: self.set_view(v))
            menu.addSeparator()
            menu.addAction("Quit", self.quit_app)
            self.tray.setContextMenu(menu)
            self._tray_menu = menu
            self.tray.show()

        self.service = QuoteService(self, store.path)
        self.service.quotes.connect(self._on_quotes)
        self.service.status.connect(lambda name, text: self.status_labels[name].setText(text))
        self.service.market.connect(self._on_market)
        self.service.history.connect(self.state.set_history)
        self._reload()
        key, secret = settings.load_keys()
        self.service.start(key, secret, self.prefs.feed, self.prefs.interval)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.model.tick)
        self.timer.timeout.connect(self.state.tick)
        self.timer.start(300)
        self.market_timer = QTimer(self)                 # session can change between clock polls
        self.market_timer.timeout.connect(self._show_market)
        self.market_timer.start(15000)
        self._show_market()
        self._apply_on_top()

        self.updater = _UpdateChecker(self)
        self.updater.done.connect(self._on_update_check)
        if self.prefs.check_updates:
            QTimer.singleShot(3000, lambda: self.updater.start(False))

    # ---- views ----
    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setAttribute(Qt.WA_StyledBackground)
        bar.setStyleSheet(_BAR_CSS)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 10, 16, 10)
        h.setSpacing(14)
        title = QLabel("Argus Ticker")
        title.setFont(theme.sans(15, theme.QFont.DemiBold))
        h.addWidget(title)
        self.market_pill = QLabel()
        self.market_pill.setFont(theme.sans(12))
        h.addWidget(self.market_pill)
        h.addStretch(1)
        seg = QWidget()
        seg.setStyleSheet("QWidget#seg { background: #121821; border-radius: 8px; }" + _SEG_CSS)
        seg.setObjectName("seg")
        seg.setAttribute(Qt.WA_StyledBackground)
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.view_buttons = QButtonGroup(self)
        for v in MAIN_VIEWS:
            b = QPushButton(VIEW_LABELS[v])
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=v: self.set_view(v))
            self.view_buttons.addButton(b)
            sl.addWidget(b)
            setattr(self, f"btn_{v}", b)
        h.addWidget(seg)
        for v in ("widget", "strip"):
            b = QPushButton(VIEW_LABELS[v])
            b.setToolTip(f"Show the {VIEW_LABELS[v].lower()} (always on top)")
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton { font-size: 12px; border: 1px solid #243041; border-radius: 6px; "
                            "padding: 6px 12px; background: transparent; color: #A7B3BF; } "
                            "QPushButton:hover { color: #E6EDF3; border-color: #3A4A5E; }")
            b.clicked.connect(lambda _=False, v=v: self.set_view(v))
            h.addWidget(b)
        return bar

    def start_ui(self) -> None:
        """Show the view the user had last (main window, widget or strip)."""
        view = str(QSettings().value("ui/view", "list"))
        self.set_view(view if view in VIEW_LABELS else "list")

    def set_view(self, view: str) -> None:
        QSettings().setValue("ui/view", view)
        if view in MAIN_VIEWS:
            self.stack.setCurrentIndex(MAIN_VIEWS.index(view))
            getattr(self, f"btn_{view}").setChecked(True)
            QSettings().setValue("ui/main_view", view)
            for a in self.view_actions.actions():
                a.setChecked(a.data() == view)
            self._show_main(keep_view=True)
            return
        (self.strip_win if view == "widget" else self.widget_win).hide()
        win = self.widget_win if view == "widget" else self.strip_win
        if view == "strip":
            self.strip_win.place()
        win.show()
        win.raise_()
        self.hide()

    def _show_main(self, keep_view: bool = False) -> None:
        if not keep_view:
            v = str(QSettings().value("ui/main_view", "list"))
            self.stack.setCurrentIndex(MAIN_VIEWS.index(v if v in MAIN_VIEWS else "list"))
            getattr(self, f"btn_{v if v in MAIN_VIEWS else 'list'}").setChecked(True)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_main()

    def _edit_by_id(self, entry_id: int) -> None:
        self.set_view("edit")
        self._select(entry_id)
        self.edit_entry()

    # ---- actions ----
    def _build_actions(self) -> QToolBar:
        tb = QToolBar("Edit")
        tb.setMovable(False)
        self.act_add = self._action("Add", QKeySequence.New, self.add_entry, tb)
        self.act_edit = self._action("Edit", QKeySequence(Qt.Key_Return), self.edit_entry, tb)
        self.act_delete = self._action("Delete", QKeySequence.Delete, self.delete_entry, tb)
        tb.addSeparator()
        self.act_up = self._action("Move up", QKeySequence("Ctrl+Up"), lambda: self.move_entry(-1), tb)
        self.act_down = self._action("Move down", QKeySequence("Ctrl+Down"), lambda: self.move_entry(1), tb)
        tb.addSeparator()
        self._action("Settings", QKeySequence.Preferences, self.open_settings, tb)
        return tb

    def _action(self, text, shortcut, slot, toolbar=None) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(shortcut)
        a.triggered.connect(slot)
        if toolbar is not None:
            toolbar.addAction(a)
        return a

    def _build_menus(self) -> None:
        f = self.menuBar().addMenu("&File")
        f.addAction(self._action("Export watchlist…", QKeySequence("Ctrl+E"), self.export_watchlist))
        f.addAction(self._action("Import watchlist…", QKeySequence("Ctrl+I"), self.import_watchlist))
        f.addSeparator()
        f.addAction(self._action("Open data folder", None, self.open_data_folder))
        f.addSeparator()
        f.addAction(self._action("Quit", QKeySequence.Quit, self.quit_app))
        v = self.menuBar().addMenu("&View")
        self.view_actions = QActionGroup(self)
        for key, shortcut in (("cards", "Ctrl+1"), ("list", "Ctrl+2"), ("edit", "Ctrl+3")):
            a = self._action(VIEW_LABELS[key], QKeySequence(shortcut), lambda _=False, k=key: self.set_view(k))
            a.setCheckable(True)
            a.setData(key)
            self.view_actions.addAction(a)
            v.addAction(a)
        v.addSeparator()
        v.addAction(self._action("Floating widget", QKeySequence("Ctrl+4"), lambda: self.set_view("widget")))
        v.addAction(self._action("Ticker strip", QKeySequence("Ctrl+5"), lambda: self.set_view("strip")))
        v.addSeparator()
        v.addAction(self._action("Alerts…", QKeySequence("Ctrl+L"), self.show_alerts))
        v.addAction(self._action("Settings…", None, self.open_settings))
        h = self.menuBar().addMenu("&Help")
        h.addAction(self._action("Check for updates…", None, lambda: self.updater.start(True)))
        h.addAction(self._action("About Argus Ticker", None, self.about))

    # ---- file / help ----
    def export_watchlist(self) -> None:
        name = f"argus-ticker-watchlist-{datetime.now():%Y-%m-%d}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export watchlist", str(Path.home() / name),
                                              "JSON (*.json);;CSV for Excel (*.csv)")
        if path:
            try:
                transfer.export_entries(self.store.list(), path)
            except OSError as e:
                QMessageBox.critical(self, "Export", f"Couldn't write the file: {e}")
                return
            self.statusBar().showMessage(f"Exported {len(self.model.entries)} entries to {path}", 8000)

    def import_watchlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import watchlist", str(Path.home()),
                                              "Watchlist (*.json *.csv)")
        if not path:
            return
        try:
            entries, problems = transfer.read_entries(path)
        except Exception as e:                           # noqa: BLE001 — bad JSON/CSV, unreadable file
            QMessageBox.critical(self, "Import", f"Couldn't read the file: {e}")
            return
        added, skipped = transfer.import_entries(self.store, entries)
        self._reload()
        lines = [f"Added {added} entr{'y' if added == 1 else 'ies'}."]
        if skipped:
            lines.append(f"Already in the list (skipped): {', '.join(skipped)}")
        if problems:
            lines.append("Not imported:\n" + "\n".join(problems[:15]) + ("\n…" if len(problems) > 15 else ""))
        QMessageBox.information(self, "Import", "\n\n".join(lines))

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(default_path().parent)))

    def about(self) -> None:
        QMessageBox.about(self, "About Argus Ticker",
                          f"<b>Argus Ticker {__version__}</b><br><br>"
                          "Crypto: Coinbase (live). Stocks: Alpaca (your keys).<br>"
                          f"Watchlist: {default_path()}<br><br>"
                          f'<a href="{updates.RELEASES_PAGE}">Releases</a>')

    def _on_update_check(self, info, manual: bool) -> None:
        if info is None:
            if manual:
                QMessageBox.information(self, "Updates", "Couldn't check for updates (offline, or the "
                                        f"releases page isn't public).\n\n{updates.RELEASES_PAGE}")
        elif info.newer:
            self._offer_update(info)
        elif manual:
            QMessageBox.information(self, "Updates", f"You have the latest version ({__version__}).")

    def _offer_update(self, info) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setIcon(QMessageBox.Information)
        box.setText(f"<b>Argus Ticker {info.latest}</b> is available (you have {__version__}).")
        box.setInformativeText("Your watchlist, settings and keys are kept.")
        install = None
        if selfupdate.can_self_update() and info.installable:
            install = box.addButton("Download and install", QMessageBox.AcceptRole)
        page = box.addButton("What's new / download page", QMessageBox.HelpRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.setDefaultButton(install or page)
        box.exec()
        if box.clickedButton() is install and install is not None:
            self._install_update(info)
        elif box.clickedButton() is page:
            QDesktopServices.openUrl(QUrl(info.url))

    def _install_update(self, info) -> None:
        self._show_main()
        dlg = QProgressDialog(f"Downloading Argus Ticker {info.latest}…", "Cancel", 0, 100, self)
        dlg.setWindowTitle("Updating")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        job = _Installer(info, self)
        self._installer = job

        def progress(done: int, total: int) -> None:
            if total:
                dlg.setMaximum(100)
                dlg.setValue(int(done * 100 / total))
            else:
                dlg.setMaximum(0)                # unknown size: busy indicator
            dlg.setLabelText(f"Downloading Argus Ticker {info.latest}… {done / 1e6:.1f} MB")

        def finished(error) -> None:
            dlg.close()
            self._installer = None
            if error:
                if not job.cancelled:
                    QMessageBox.warning(self, "Update", f"The update wasn't installed:\n\n{error}\n\n"
                                        f"You can download it by hand from\n{info.url}")
                return
            QMessageBox.information(self, "Update", f"Argus Ticker {info.latest} is installed. "
                                    "The app will now restart.")
            try:
                selfupdate.relaunch(selfupdate.current_exe())
            except Exception as e:               # noqa: BLE001
                QMessageBox.warning(self, "Update", f"Installed, but couldn't restart automatically ({e}). "
                                    "Please start Argus Ticker again.")
            self.quit_app()

        job.progress.connect(progress)
        job.done.connect(finished)
        dlg.canceled.connect(lambda: setattr(job, "cancelled", True))
        job.start()

    # ---- market session ----
    def _on_market(self, m) -> None:
        self.market = m
        self.state.set_market(m)
        self._show_market()

    def _show_market(self) -> None:
        session = self.market.session(datetime.now(market.ET))
        self.model.set_stocks_live(session == market.OPEN)
        self.state.refresh_session()
        self.market_pill.setText(f"●  {self.market.label()}")
        self.market_pill.setStyleSheet(f"color: {self.state.market_color().name()}; background: #161D27; "
                                       "border-radius: 10px; padding: 3px 10px;")

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        if self.table.indexAt(pos).isValid():
            for a in (self.act_edit, self.act_delete, self.act_up, self.act_down):
                menu.addAction(a)
            menu.addSeparator()
        menu.addAction(self.act_add)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.model.entry_at(rows[0].row()) if rows else None

    def _select(self, entry_id) -> None:
        for row, e in enumerate(self.model.entries):
            if e.id == entry_id:
                self.table.selectRow(row)

    def _reload(self, select_id=None) -> None:
        entries = self.store.list()
        self.model.set_entries(entries)
        self.state.set_entries(entries)
        self.service.set_watchlist(entries)
        if select_id is not None:
            self._select(select_id)

    def add_entry(self) -> None:
        dlg = EntryDialog(self, keys=settings.load_keys, feed=self.prefs.feed)
        if dlg.exec() and dlg.result_entry:
            try:
                e = self.store.add(dlg.result_entry)
            except DuplicateEntry as err:
                QMessageBox.information(self, "Add", str(err))
                return
            self._reload(e.id)

    def edit_entry(self) -> None:
        cur = self._selected()
        if not cur:
            return
        dlg = EntryDialog(self, cur, keys=settings.load_keys, feed=self.prefs.feed)
        if dlg.exec() and dlg.result_entry:
            try:
                self.store.update(dlg.result_entry)
            except DuplicateEntry as err:
                QMessageBox.information(self, "Edit", str(err))
                return
            self.alerts.forget(cur.id)
            self._reload(cur.id)

    def delete_entry(self) -> None:
        cur = self._selected()
        if cur and QMessageBox.question(self, "Delete", f"Remove {cur.symbol} from the list?") == QMessageBox.Yes:
            self.store.delete(cur.id)
            self.alerts.forget(cur.id)
            self._reload()

    def move_entry(self, delta: int) -> None:
        cur = self._selected()
        if cur:
            self.store.move(cur.id, delta)
            self._reload(cur.id)

    def open_settings(self) -> None:
        key, _ = settings.load_keys()
        dlg = SettingsDialog(self, self.prefs, has_keys=bool(key))
        if dlg.exec():
            old, self.prefs = self.prefs, dlg.prefs
            if dlg.keys_changed or (old.feed, old.interval) != (self.prefs.feed, self.prefs.interval):
                key, secret = settings.load_keys()
                self.service.configure_alpaca(key, secret, self.prefs.feed, self.prefs.interval)
            self.state.set_scheme(self.prefs.scheme)
            self._apply_on_top()

    def _apply_on_top(self) -> None:
        on = self.prefs.always_on_top
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) != on:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
            self.show()

    # ---- quotes ----
    def _on_quotes(self, quotes) -> None:
        self.model.update_quotes(quotes)
        self.state.update_quotes(quotes)
        by_key = {(q.symbol, q.kind): q for q in quotes}
        new = []
        for e in self.model.entries:
            q = by_key.get((e.symbol, e.kind))
            if q:
                new.extend(self.alerts.check(e, q.price))
        for a in new:                                     # each alert notifies once; repeats wait for you
            self.statusBar().showMessage(a.text(), 15000)
            if self.tray:
                self.tray.showMessage("Price alert", a.text() + "\nClick to snooze or turn it off.",
                                      QSystemTrayIcon.Information, 10000)
        if new and self.prefs.alert_popup:
            self.show_alerts()
        elif self.alerts_win and self.alerts_win.isVisible():
            self.alerts_win.refresh()

    # ---- alerts ----
    def show_alerts(self) -> None:
        if self.alerts_win is None:
            self.alerts_win = AlertsWindow(self, self.alerts, self.turn_off_alert,
                                           lambda: self.prefs.alert_snooze_min)
        self.alerts_win.refresh()
        if not self.alerts.pending:
            self.statusBar().showMessage("No alerts waiting.", 5000)
            return
        self.alerts_win.show()
        self.alerts_win.raise_()
        self.alerts_win.activateWindow()

    def turn_off_alert(self, key) -> None:
        """Clear that alert level on the entry (saved), and drop the waiting alert."""
        entry_id, side = key
        e = self.store.get(entry_id)
        self.alerts.pending.pop(key, None)
        if e is None:
            return
        if side == "above":
            e.alert_above = None
        else:
            e.alert_below = None
        self.store.update(e)
        self._reload(entry_id)
        self.statusBar().showMessage(f"Alert {side} turned off for {e.symbol}.", 8000)

    def closeEvent(self, event) -> None:
        if self.widget_win.isVisible() or self.strip_win.isVisible():
            self.hide()                                   # an overlay keeps the app running
            event.ignore()
            return
        self.quit_app()

    def quit_app(self) -> None:
        if getattr(self, "_quitting", False):
            return
        self._quitting = True
        self.service.stop()
        for w in (self.widget_win, self.strip_win):
            w.close()
        if self.tray:
            self.tray.hide()
        QApplication.quit()
