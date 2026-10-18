"""Spot precious metals (USD per troy ounce) from Swissquote's public price feed.

The feed gives the current bid/ask only, so the provider keeps its own
readings (one per metal per 5 minutes, in the ``metal_ticks`` table of the
watchlist database) and derives the daily change and trend line from them.
Until the app has seen a daily close (5 PM ET), the change is unknown.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from .. import market as mkt
from ..db import migrate
from ..models import METAL, METALS, Quote
from .base import Emit, HttpError, Status, as_float, http_get_json

FEED_URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{sym}/USD"
BUCKET = 300                    # one stored reading per 5 minutes
KEEP_DAYS = 8
REF_WINDOW = 6 * 3600           # a reading up to 6 h before a close stands in for it
_log = logging.getLogger("ticker.metals")


def parse_bbo(data: list) -> Optional[tuple[float, float, float, float]]:
    """Feed response → (mid, bid, ask, epoch s), preferring Swissquote's own 'prime' prices."""
    best = None
    for platform in data or []:
        profiles = {p.get("spreadProfile"): p for p in platform.get("spreadProfilePrices") or []}
        prof = profiles.get("prime") or next(iter(profiles.values()), None)
        if not prof:
            continue
        bid, ask = as_float(prof.get("bid")), as_float(prof.get("ask"))
        if bid is None or ask is None:
            continue
        cand = ((bid + ask) / 2, bid, ask, (platform.get("ts") or 0) / 1000)
        if (platform.get("topo") or {}).get("platform") == "SwissquoteLtd":
            return cand
        best = best or cand
    return best


class TickStore:
    """The metal_ticks table, on its own connection (used from the quote thread)."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        migrate(self.conn)

    def record(self, symbol: str, ts: float, price: float) -> None:
        self.conn.execute("INSERT OR REPLACE INTO metal_ticks VALUES (?, ?, ?, ?)",
                          (symbol, int(ts // BUCKET), ts, price))
        self.conn.commit()

    def prune(self, now: float) -> None:
        self.conn.execute("DELETE FROM metal_ticks WHERE ts < ?", (now - KEEP_DAYS * 86400,))
        self.conn.commit()

    def price_at(self, symbol: str, close: datetime) -> Optional[float]:
        """Last reading at or before ``close`` (within REF_WINDOW)."""
        c = close.timestamp()
        row = self.conn.execute("SELECT price FROM metal_ticks WHERE symbol = ? AND ts <= ? AND ts > ? "
                                "ORDER BY ts DESC LIMIT 1", (symbol, c, c - REF_WINDOW)).fetchone()
        return row[0] if row else None

    def series(self, symbol: str, start: float, end: float) -> list[float]:
        rows = self.conn.execute("SELECT price FROM metal_ticks WHERE symbol = ? AND ts >= ? AND ts <= ? "
                                 "ORDER BY ts", (symbol, start, end)).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self.conn.close()


class MetalsProvider:
    name = "Metals"

    def __init__(self, emit: Emit, status: Status, db_path: str, interval: float = 5.0,
                 history: Optional[Callable[[dict], None]] = None):
        self.emit, self.status, self.interval = emit, status, interval
        self.history = history or (lambda h: None)
        self.db_path = db_path
        self.symbols: set[str] = set()
        self._wake = asyncio.Event()
        self._store: Optional[TickStore] = None

    def set_symbols(self, symbols: set[str]) -> None:
        added = symbols - self.symbols
        self.symbols = set(symbols)
        if added:
            self._wake.set()

    def quote(self, sym: str, mid: float, bid: float, ask: float, ts: float, now: datetime) -> Quote:
        ref = self._store.price_at(sym, mkt.metal_reference_close(now)) if self._store else None
        return Quote(sym, METAL, mid, ref, ts, bid, ask)

    def trend(self, sym: str, now: datetime) -> list[float]:
        end = now if mkt.metals_open(now) else mkt.last_metal_close(now)
        return self._store.series(sym, (end - timedelta(hours=24)).timestamp(), end.timestamp())

    async def poll_once(self) -> None:
        now = datetime.now(mkt.ET)
        ok = 0
        for sym in sorted(self.symbols):
            try:
                got = parse_bbo(await asyncio.to_thread(http_get_json, FEED_URL.format(sym=sym), None, 10))
            except HttpError as e:
                self.status(f"Metals: {sym} {e}")
                continue
            if not got:
                continue
            mid, bid, ask, ts = got
            ts = ts or time.time()
            self._store.record(sym, ts, mid)
            self.emit(self.quote(sym, mid, bid, ask, ts, now))
            ok += 1
        if ok:
            self.status(f"Metals: {mkt.metals_label(now).split(' · ')[0].replace('Metals ', '')}")

    async def run(self) -> None:
        self._store = TickStore(self.db_path)
        last_hist = 0.0
        delay = self.interval
        try:
            while True:
                if self.symbols:
                    try:
                        await self.poll_once()
                        delay = self.interval if mkt.metals_open() else max(self.interval, 60)
                        if time.monotonic() - last_hist > 60:
                            now = datetime.now(mkt.ET)
                            self._store.prune(time.time())
                            self.history({(s, METAL): self.trend(s, now) for s in self.symbols})
                            last_hist = time.monotonic()
                    except Exception as e:                # noqa: BLE001 — network blips: retry
                        self.status(f"Metals: retrying ({type(e).__name__})")
                        delay = min(max(delay, self.interval) * 2, 120)
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), delay)
                    last_hist = 0.0                       # new symbol: send its trend now
                except asyncio.TimeoutError:
                    pass
        finally:
            self._store.close()


def display_name(sym: str) -> str:
    return METALS.get(sym, sym)
