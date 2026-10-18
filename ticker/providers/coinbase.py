"""Crypto quotes from Coinbase Exchange's public feed (no account or key).

Live prices stream over the ``ticker`` WebSocket channel; each newly added
product first gets its 24 h stats over REST so it shows a price right away.
Change is measured against the 24 h open.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import websockets

from ..models import CRYPTO, Quote
from .base import Emit, HttpError, Status, as_float, http_get_json, parse_time

WS_URL = "wss://ws-feed.exchange.coinbase.com"
REST_URL = "https://api.exchange.coinbase.com"
_log = logging.getLogger("ticker.coinbase")


def parse_ticker(msg: dict) -> Optional[Quote]:
    if msg.get("type") != "ticker" or as_float(msg.get("price")) is None:
        return None
    return Quote(msg["product_id"], CRYPTO, float(msg["price"]), as_float(msg.get("open_24h")),
                 parse_time(msg.get("time")), as_float(msg.get("best_bid")), as_float(msg.get("best_ask")))


def parse_stats(product: str, stats: dict) -> Optional[Quote]:
    price = as_float(stats.get("last"))
    return None if price is None else Quote(product, CRYPTO, price, as_float(stats.get("open")))


def validate(product: str) -> bool:
    """True if Coinbase lists the product (blocking; raises on network errors)."""
    try:
        http_get_json(f"{REST_URL}/products/{product}", timeout=8)
        return True
    except HttpError as e:
        if e.code in (400, 404):
            return False
        raise


class CoinbaseProvider:
    name = "Coinbase"

    def __init__(self, emit: Emit, status: Status):
        self.emit, self.status = emit, status
        self.symbols: set[str] = set()
        self._ws = None

    def set_symbols(self, symbols: set[str]) -> None:
        added, removed = symbols - self.symbols, self.symbols - symbols
        self.symbols = set(symbols)
        if added:
            asyncio.create_task(self._snapshot(sorted(added)))
        if self._ws is not None:
            if added:
                asyncio.create_task(self._send("subscribe", sorted(added)))
            if removed:
                asyncio.create_task(self._send("unsubscribe", sorted(removed)))

    async def _snapshot(self, products: list[str]) -> None:
        for p in products:
            try:
                q = parse_stats(p, await asyncio.to_thread(http_get_json, f"{REST_URL}/products/{p}/stats"))
            except Exception as e:                       # noqa: BLE001 — the stream will fill it in
                _log.warning("stats %s: %s", p, e)
                continue
            if q and p in self.symbols:
                self.emit(q)

    async def _send(self, action: str, products: list[str]) -> None:
        try:
            await self._ws.send(json.dumps({"type": action, "product_ids": products, "channels": ["ticker"]}))
        except Exception as e:                           # noqa: BLE001 — reconnect resubscribes
            _log.warning("%s failed: %s", action, e)

    async def run(self) -> None:
        delay = 1
        while True:
            if not self.symbols:
                await asyncio.sleep(1)
                continue
            try:
                async with websockets.connect(WS_URL, ping_interval=20, max_size=2**22) as ws:
                    self._ws = ws
                    await self._send("subscribe", sorted(self.symbols))
                    self.status("Coinbase: live")
                    delay = 1
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") == "error":
                            self.status(f"Coinbase: {msg.get('reason') or msg.get('message')}")
                            continue
                        q = parse_ticker(msg)
                        if q and q.symbol in self.symbols:
                            self.emit(q)
            except asyncio.CancelledError:
                raise
            except Exception as e:                       # noqa: BLE001 — any drop → reconnect
                self.status(f"Coinbase: reconnecting ({type(e).__name__})")
            finally:
                self._ws = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


def parse_candles(candles: list, now: float, hours: float = 24) -> list[float]:
    """Coinbase candles ([time, low, high, open, close, volume], newest first) → closes, oldest first."""
    rows = sorted((c for c in candles or [] if len(c) >= 5 and c[0] >= now - hours * 3600), key=lambda c: c[0])
    return [float(c[4]) for c in rows]


def fetch_history(product: str, now: float) -> list[float]:
    """Last 24 h of 15-minute closes (blocking)."""
    return parse_candles(http_get_json(f"{REST_URL}/products/{product}/candles?granularity=900", timeout=10), now)
