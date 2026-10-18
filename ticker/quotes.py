"""Quote service: runs the providers on a background asyncio loop.

The GUI calls ``set_watchlist`` / ``configure_alpaca``; updates come back
through Qt signals, batched every 250 ms so a busy crypto stream can't
flood the window.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .models import CRYPTO, STOCK, Entry, Quote
from .providers.alpaca import AlpacaProvider
from .providers.coinbase import CoinbaseProvider

FLUSH_SECONDS = 0.25


class QuoteService(QObject):
    quotes = Signal(list)            # list[Quote]
    status = Signal(str, str)        # provider name, text

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="quotes", daemon=True)
        self._pending: dict[tuple[str, str], Quote] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._providers: dict[str, object] = {}
        self._symbols = {STOCK: set(), CRYPTO: set()}

    # ---- called from the GUI thread ----
    def start(self, alpaca_key: Optional[str], alpaca_secret: Optional[str], feed: str, interval: float) -> None:
        self._thread.start()
        self._call(self._start, alpaca_key, alpaca_secret, feed, interval)

    def stop(self) -> None:
        if self._thread.is_alive():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)

    def set_watchlist(self, entries: list[Entry]) -> None:
        stocks = {e.symbol for e in entries if e.kind == STOCK}
        crypto = {e.symbol for e in entries if e.kind == CRYPTO}
        self._call(self._set_symbols, stocks, crypto)

    def configure_alpaca(self, key: Optional[str], secret: Optional[str], feed: str, interval: float) -> None:
        self._call(self._start_alpaca, key, secret, feed, interval)

    def _call(self, fn, *args) -> None:
        self._loop.call_soon_threadsafe(fn, *args)

    # ---- on the loop ----
    def _start(self, key, secret, feed, interval) -> None:
        self._providers[CRYPTO] = cb = CoinbaseProvider(self._emit, lambda t: self.status.emit("Coinbase", t))
        cb.set_symbols(self._symbols[CRYPTO])
        self._tasks[CRYPTO] = self._loop.create_task(cb.run())
        self._start_alpaca(key, secret, feed, interval)
        self._tasks["flush"] = self._loop.create_task(self._flusher())

    def _start_alpaca(self, key, secret, feed, interval) -> None:
        if STOCK in self._tasks:
            self._tasks.pop(STOCK).cancel()
        self._providers[STOCK] = ap = AlpacaProvider(self._emit, lambda t: self.status.emit("Alpaca", t),
                                                     key, secret, feed, interval)
        ap.set_symbols(self._symbols[STOCK])
        self._tasks[STOCK] = self._loop.create_task(ap.run())

    def _set_symbols(self, stocks: set[str], crypto: set[str]) -> None:
        self._symbols = {STOCK: stocks, CRYPTO: crypto}
        for kind, p in self._providers.items():
            p.set_symbols(self._symbols[kind])
        for key in [k for k in self._pending if k[0] not in self._symbols[k[1]]]:
            del self._pending[key]

    def _emit(self, q: Quote) -> None:
        self._pending[(q.symbol, q.kind)] = q

    async def _flusher(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            if self._pending:
                batch, self._pending = list(self._pending.values()), {}
                self.quotes.emit(batch)

    async def _shutdown(self) -> None:
        for t in self._tasks.values():
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
