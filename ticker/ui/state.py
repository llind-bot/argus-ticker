"""Shared live state for the views: entries, quotes, trend history, market session."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from .. import format as fmt
from .. import market
from ..models import CRYPTO, STOCK, Entry, Quote
from . import theme

FLASH_SECONDS = 0.8


@dataclass
class Row:
    """Everything a view needs to draw one entry."""
    entry: Entry
    symbol: str
    short: str                    # BTC-USD → BTC (ticker strip)
    name: str
    price: str
    change: str
    pct: str
    up: Optional[bool]            # None: no change data yet
    color: QColor
    live: bool                    # False: stock outside the regular session
    points: list[float]
    flash: int                    # +1 / -1 while the price just moved, else 0
    has_quote: bool


class LiveState(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[Entry] = []
        self.quotes: dict[tuple[str, str], Quote] = {}
        self.history: dict[tuple[str, str], list[float]] = {}
        self.market = market.estimate()
        self.session = self.market.session(market.datetime.now(market.ET))
        self.scheme = "green-red"
        self._flash: dict[tuple[str, str], tuple[float, int]] = {}

    @property
    def up_color(self) -> QColor:
        return theme.SCHEMES.get(self.scheme, theme.SCHEMES["green-red"])[0]

    @property
    def down_color(self) -> QColor:
        return theme.SCHEMES.get(self.scheme, theme.SCHEMES["green-red"])[1]

    @property
    def stocks_live(self) -> bool:
        return self.session == market.OPEN

    # ---- updates ----
    def set_entries(self, entries: list[Entry]) -> None:
        self.entries = list(entries)
        keep = {(e.symbol, e.kind) for e in entries}
        self.quotes = {k: v for k, v in self.quotes.items() if k in keep}
        self.changed.emit()

    def update_quotes(self, quotes: list[Quote]) -> None:
        now = time.monotonic()
        for q in quotes:
            key = (q.symbol, q.kind)
            old = self.quotes.get(key)
            if old and q.price != old.price:
                self._flash[key] = (now + FLASH_SECONDS, 1 if q.price > old.price else -1)
            self.quotes[key] = q
        self.changed.emit()

    def set_history(self, history: dict) -> None:
        self.history.update(history)
        self.changed.emit()

    def set_market(self, m: market.Market) -> None:
        self.market = m
        self.refresh_session()

    def refresh_session(self) -> None:
        self.session = self.market.session(market.datetime.now(market.ET))
        self.changed.emit()

    def set_scheme(self, scheme: str) -> None:
        self.scheme = scheme
        self.changed.emit()

    def tick(self) -> None:
        """Timer: end finished flashes."""
        now = time.monotonic()
        if any(v[0] <= now for v in self._flash.values()):
            self._flash = {k: v for k, v in self._flash.items() if v[0] > now}
            self.changed.emit()

    # ---- for the views ----
    def market_label(self) -> str:
        return self.market.label()

    def market_color(self) -> QColor:
        return {market.OPEN: self.up_color, market.PRE: theme.PRE_POST,
                market.POST: theme.PRE_POST}.get(self.session, theme.CLOSED)

    def rows(self, kind: Optional[str] = None) -> list[Row]:
        return [self.row(e) for e in self.entries if kind is None or e.kind == kind]

    def row(self, e: Entry) -> Row:
        key = (e.symbol, e.kind)
        q = self.quotes.get(key)
        up = None if q is None or q.change is None else q.change >= 0
        color = theme.MUTED if up is None else (self.up_color if up else self.down_color)
        points = list(self.history.get(key, []))
        if q and points:
            points.append(q.price)                        # line ends at the live price
        flash = self._flash.get(key)
        short = e.symbol.split("-")[0] if e.kind == CRYPTO else e.symbol
        return Row(e, e.symbol, short, e.name, fmt.price(q.price) if q else "…",
                   fmt.change(q.change, q.price) if q else "", fmt.pct(q.change_pct) if q else "",
                   up, color, e.kind != STOCK or self.stocks_live, points,
                   flash[1] if flash and flash[0] > time.monotonic() else 0, q is not None)
