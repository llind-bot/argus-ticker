"""Main window: the watchlist table, toolbar, status bar and tray alerts."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSystemTrayIcon, QTableView, QToolBar)

from .. import settings
from ..db import DuplicateEntry, Store
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


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.prefs = settings.load_prefs()
        self.alerts = AlertTracker()
        self.setWindowTitle("Argus Ticker")
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
        self._reload()
        key, secret = settings.load_keys()
        self.service.start(key, secret, self.prefs.feed, self.prefs.interval)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.model.tick)
        self.timer.start(300)
        self._apply_on_top()

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

    def _action(self, text, shortcut, slot, toolbar) -> QAction:
        a = QAction(text, self)
        a.setShortcut(shortcut)
        a.triggered.connect(slot)
        toolbar.addAction(a)
        return a

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
