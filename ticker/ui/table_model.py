"""Table model: one row per watchlist entry, with its latest quote."""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from .. import format as fmt
from ..models import CRYPTO, STOCK, Entry, Quote

COLUMNS = ["Symbol", "Name", "Price", "Change", "Change %", "Bid", "Ask", "Updated"]
NUMERIC = {2, 3, 4, 5, 6, 7}
FLASH_SECONDS = 0.8
UP, DOWN = QColor(22, 163, 74), QColor(220, 38, 38)
UP_BG, DOWN_BG = QColor(22, 163, 74, 70), QColor(220, 38, 38, 70)
GREY = QColor(128, 128, 128)
UP_DIM, DOWN_DIM = QColor(22, 163, 74, 140), QColor(220, 38, 38, 140)


class WatchlistModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[Entry] = []
        self.quotes: dict[tuple[str, str], Quote] = {}
        self._flash: dict[tuple[str, str], tuple[float, int]] = {}   # key → (until, +1/-1)
        self.stocks_live = True                                       # False: market closed → grey stock rows
        self._bold = QFont()
        self._bold.setBold(True)

    # ---- data in ----
    def set_entries(self, entries: list[Entry]) -> None:
        self.beginResetModel()
        self.entries = list(entries)
        keep = {(e.symbol, e.kind) for e in entries}
        self.quotes = {k: v for k, v in self.quotes.items() if k in keep}
        self.endResetModel()

    def update_quotes(self, quotes: list[Quote]) -> None:
        now = time.monotonic()
        for q in quotes:
            key = (q.symbol, q.kind)
            old = self.quotes.get(key)
            if old and q.price != old.price:
                self._flash[key] = (now + FLASH_SECONDS, 1 if q.price > old.price else -1)
            self.quotes[key] = q
        self._refresh_all()

    def tick(self) -> None:
        """Called by a timer: clear finished flashes and refresh the 'Updated' ages."""
        now = time.monotonic()
        self._flash = {k: v for k, v in self._flash.items() if v[0] > now}
        self._refresh_all()

    def _refresh_all(self) -> None:
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, len(COLUMNS) - 1))

    def set_stocks_live(self, live: bool) -> None:
        if live != self.stocks_live:
            self.stocks_live = live
            self._refresh_all()

    def entry_at(self, row: int) -> Optional[Entry]:
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def quote_for(self, e: Entry) -> Optional[Quote]:
        return self.quotes.get((e.symbol, e.kind))

    # ---- Qt model API ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return COLUMNS[section]
        if role == Qt.TextAlignmentRole and section in NUMERIC:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole and section in (3, 4):
            return "Stocks: since the previous close. Crypto: over the last 24 hours."
        return None

    def data(self, index, role=Qt.DisplayRole):
        e = self.entry_at(index.row())
        if e is None:
            return None
        col, q = index.column(), self.quote_for(e)
        if role == Qt.DisplayRole:
            return self._text(e, q, col)
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if col in NUMERIC else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            dim = e.kind == STOCK and not self.stocks_live
            if q and col in (3, 4) and q.change:
                return QBrush((UP_DIM if dim else UP) if q.change > 0 else (DOWN_DIM if dim else DOWN))
            return QBrush(GREY) if dim else None
        if role == Qt.BackgroundRole and col == 2:
            flash = self._flash.get((e.symbol, e.kind))
            if flash:
                return QBrush(UP_BG if flash[1] > 0 else DOWN_BG)
        if role == Qt.FontRole and col in (0, 2):
            return self._bold
        if role == Qt.ToolTipRole:
            tip = f"{e.symbol} ({'crypto · Coinbase' if e.kind == CRYPTO else 'stock · Alpaca'})"
            alerts = [f"alert above {fmt.price(e.alert_above)}" if e.alert_above is not None else "",
                      f"alert below {fmt.price(e.alert_below)}" if e.alert_below is not None else ""]
            extra = [x for x in alerts + [e.notes] if x]
            return "\n".join([tip] + extra)
        return None

    @staticmethod
    def _text(e: Entry, q: Optional[Quote], col: int) -> str:
        if col == 0:
            return e.symbol + ("  🔔" if e.alert_above is not None or e.alert_below is not None else "")
        if col == 1:
            return e.name
        if q is None:
            return "…" if col == 2 else ""
        return [None, None, fmt.price(q.price), fmt.change(q.change, q.price), fmt.pct(q.change_pct),
                fmt.price(q.bid) if q.bid else "—", fmt.price(q.ask) if q.ask else "—", fmt.age(q.ts)][col]
