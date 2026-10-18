"""Main window: the watchlist table, toolbar, status bar and tray alerts."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHeaderView, QLabel, QMainWindow,
                               QMenu, QMessageBox, QSystemTrayIcon, QTableView, QToolBar)

from .. import __version__, market, settings, transfer, updates
from ..db import DuplicateEntry, Store, default_path
from ..format import AlertTracker
from ..quotes import QuoteService
from .dialogs import EntryDialog, SettingsDialog
from .table_model import WatchlistModel


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


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.prefs = settings.load_prefs()
        self.alerts = AlertTracker()
        self.setWindowTitle(f"Argus Ticker {__version__}")
        self.market = market.estimate()
        self.setWindowIcon(app_icon())
        self.resize(820, 420)

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
        self.setCentralWidget(self.table)

        self._build_actions()
        self._build_menus()
        self.market_label = QLabel()
        self.statusBar().addWidget(self.market_label)
        self.status_labels = {name: QLabel(f"{name}: idle") for name in ("Alpaca", "Coinbase")}
        for lbl in self.status_labels.values():
            self.statusBar().addPermanentWidget(lbl)

        self.tray = QSystemTrayIcon(app_icon(), self) if QSystemTrayIcon.isSystemTrayAvailable() else None
        if self.tray:
            self.tray.setToolTip("Argus Ticker")
            self.tray.activated.connect(lambda *_: (self.showNormal(), self.activateWindow()))
            self.tray.show()

        self.service = QuoteService(self)
        self.service.quotes.connect(self._on_quotes)
        self.service.status.connect(lambda name, text: self.status_labels[name].setText(text))
        self.service.market.connect(self._on_market)
        self._reload()
        key, secret = settings.load_keys()
        self.service.start(key, secret, self.prefs.feed, self.prefs.interval)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.model.tick)
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

    # ---- actions ----
    def _build_actions(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_add = self._action("Add", QKeySequence.New, self.add_entry, tb)
        self.act_edit = self._action("Edit", QKeySequence(Qt.Key_Return), self.edit_entry, tb)
        self.act_delete = self._action("Delete", QKeySequence.Delete, self.delete_entry, tb)
        tb.addSeparator()
        self.act_up = self._action("Move up", QKeySequence("Ctrl+Up"), lambda: self.move_entry(-1), tb)
        self.act_down = self._action("Move down", QKeySequence("Ctrl+Down"), lambda: self.move_entry(1), tb)
        tb.addSeparator()
        self._action("Settings", QKeySequence.Preferences, self.open_settings, tb)

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
        f.addAction(self._action("Quit", QKeySequence.Quit, self.close))
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
            if QMessageBox.question(self, "Update available",
                                    f"Argus Ticker {info.latest} is available (you have {__version__}).\n\n"
                                    "Open the download page? Your watchlist and settings are kept "
                                    "when you replace the app.") == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(info.url))
        elif manual:
            QMessageBox.information(self, "Updates", f"You have the latest version ({__version__}).")

    # ---- market session ----
    def _on_market(self, m) -> None:
        self.market = m
        self._show_market()

    def _show_market(self) -> None:
        session = self.market.session(datetime.now(market.ET))
        self.market_label.setText(self.market.label())
        color = "#16a34a" if session == market.OPEN else "#d97706" if session in (market.PRE, market.POST) else "#808080"
        self.market_label.setStyleSheet(f"color: {color}; font-weight: 600; padding: 0 6px;")
        self.model.set_stocks_live(session == market.OPEN)

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
            self._apply_on_top()

    def _apply_on_top(self) -> None:
        on = self.prefs.always_on_top
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) != on:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
            self.show()

    # ---- quotes ----
    def _on_quotes(self, quotes) -> None:
        self.model.update_quotes(quotes)
        by_key = {(q.symbol, q.kind): q for q in quotes}
        for e in self.model.entries:
            q = by_key.get((e.symbol, e.kind))
            if q:
                for msg in self.alerts.check(e, q.price):
                    self.statusBar().showMessage(msg, 15000)
                    if self.tray:
                        self.tray.showMessage("Price alert", msg, QSystemTrayIcon.Information, 10000)

    def closeEvent(self, event) -> None:
        self.service.stop()
        if self.tray:
            self.tray.hide()
        super().closeEvent(event)
