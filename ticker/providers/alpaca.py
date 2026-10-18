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

from .. import market as mkt
from ..models import STOCK, Quote
from .base import Emit, HttpError, Status, as_float, http_get_json, parse_time

DATA_URL = "https://data.alpaca.markets/v2/stocks"
TRADING_URLS = ("https://paper-api.alpaca.markets", "https://api.alpaca.markets")   # paper or live keys
CLOCK_SECONDS = 60
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
                 feed: str = "iex", interval: float = 5.0, market=None):
        self.emit, self.status = emit, status
        self.market = market or (lambda m: None)        # called with a market.Market
        self._trading_url: Optional[str] = None
        self._calendar: tuple[Optional[str], list] = (None, [])
        self._clock_at = 0.0
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

    async def update_market(self) -> None:
        """Market session from Alpaca's clock/calendar (estimated without keys or on errors)."""
        loop = asyncio.get_running_loop()
        if loop.time() - self._clock_at < CLOCK_SECONDS and self._clock_at:
            return
        self._clock_at = loop.time()
        if not (self.key and self.secret):
            self.market(mkt.estimate())
            return
        h = _headers(self.key, self.secret)
        try:
            for base in ([self._trading_url] if self._trading_url else TRADING_URLS):
                try:
                    clock = await asyncio.to_thread(http_get_json, f"{base}/v2/clock", h, 8)
                    self._trading_url = base
                    break
                except HttpError as e:
                    if e.code not in (401, 403) or base == TRADING_URLS[-1]:
                        raise
            today = mkt.datetime.now(mkt.ET).date().isoformat()
            if self._calendar[0] != today:
                cal = await asyncio.to_thread(http_get_json, f"{self._trading_url}/v2/calendar?start={today}&end={today}", h, 8)
                self._calendar = (today, cal)
            self.market(mkt.from_alpaca(clock, self._calendar[1]))
        except Exception as e:                            # noqa: BLE001 — fall back to the weekday rule
            _log.warning("market clock: %s", e)
            self.market(mkt.estimate())

    async def run(self) -> None:
        delay = self.interval
        while True:
            await self.update_market()
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
