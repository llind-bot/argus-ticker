"""Stock quotes from Alpaca's market-data snapshots (user's own API keys).

Polled over REST rather than streamed: an Alpaca account gets one stock
stream connection, and another program (e.g. a trading bot) may already
hold it. One request per poll covers every symbol. Change is measured
against the previous session's close.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Optional

from ..models import STOCK, Quote
from .base import Emit, HttpError, Status, as_float, http_get_json, parse_time

DATA_URL = "https://data.alpaca.markets/v2/stocks"
FEEDS = ("iex", "sip")          # iex: free plan; sip: all US exchanges (paid plan)
_log = logging.getLogger("ticker.alpaca")


def parse_snapshots(data: dict) -> list[Quote]:
    out = []
    for sym, snap in (data or {}).items():
        if not snap:
            continue
        trade = snap.get("latestTrade") or {}
        price = as_float(trade.get("p")) or as_float((snap.get("dailyBar") or {}).get("c"))
        if price is None:
            continue
        quote = snap.get("latestQuote") or {}
        out.append(Quote(sym, STOCK, price, as_float((snap.get("prevDailyBar") or {}).get("c")),
                         parse_time(trade.get("t")), as_float(quote.get("bp")), as_float(quote.get("ap"))))
    return out


def _headers(key: str, secret: str) -> dict:
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def validate(symbol: str, key: str, secret: str, feed: str = "iex") -> bool:
    """True if Alpaca has data for the symbol (blocking; raises on auth/network errors)."""
    try:
        http_get_json(f"{DATA_URL}/{urllib.parse.quote(symbol)}/snapshot?feed={feed}", _headers(key, secret), 8)
        return True
    except HttpError as e:
        if e.code in (400, 404, 422):
            return False
        raise


class AlpacaProvider:
    name = "Alpaca"

    def __init__(self, emit: Emit, status: Status, key: Optional[str], secret: Optional[str],
                 feed: str = "iex", interval: float = 5.0):
        self.emit, self.status = emit, status
        self.key, self.secret, self.feed, self.interval = key, secret, feed, interval
        self.symbols: set[str] = set()
        self._wake = asyncio.Event()

    def set_symbols(self, symbols: set[str]) -> None:
        added = symbols - self.symbols
        self.symbols = set(symbols)
        if added:
            self._wake.set()                              # poll now so new rows fill in

    async def poll_once(self) -> None:
        url = f"{DATA_URL}/snapshots?" + urllib.parse.urlencode(
            {"symbols": ",".join(sorted(self.symbols)), "feed": self.feed})
        data = await asyncio.to_thread(http_get_json, url, _headers(self.key, self.secret))
        for q in parse_snapshots(data):
            if q.symbol in self.symbols:
                self.emit(q)

    async def run(self) -> None:
        delay = self.interval
        while True:
            if self.symbols and not (self.key and self.secret):
                self.status("Alpaca: add your API keys in Settings")
            elif self.symbols:
                try:
                    await self.poll_once()
                    self.status(f"Alpaca ({self.feed.upper()}): every {self.interval:g}s")
                    delay = self.interval
                except HttpError as e:
                    if e.code in (401, 403):
                        self.status("Alpaca: keys rejected — check Settings")
                    elif e.code == 429:
                        self.status("Alpaca: rate limited, slowing down")
                    else:
                        self.status(f"Alpaca: {e}")
                    delay = min(max(delay, self.interval) * 2, 120)
                except Exception as e:                    # noqa: BLE001 — network blips: retry
                    self.status(f"Alpaca: retrying ({type(e).__name__})")
                    delay = min(max(delay, self.interval) * 2, 120)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except asyncio.TimeoutError:
                pass
