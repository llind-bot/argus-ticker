"""Watchlist entries and quotes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

STOCK, CRYPTO, METAL = "stock", "crypto", "metal"
KINDS = (STOCK, CRYPTO, METAL)
METALS = {"XAU": "Gold", "XAG": "Silver", "XPT": "Platinum", "XPD": "Palladium"}   # spot, USD per troy oz
_METAL_WORDS = {v.upper(): k for k, v in METALS.items()}


@dataclass
class Entry:
    id: Optional[int]
    symbol: str
    kind: str                         # STOCK, CRYPTO or METAL
    name: str = ""
    notes: str = ""
    alert_above: Optional[float] = None
    alert_below: Optional[float] = None
    sort: int = 0


@dataclass
class Quote:
    symbol: str
    kind: str
    price: float
    reference: Optional[float] = None   # previous close (stocks) or 24 h open (crypto)
    ts: float = 0.0                     # epoch seconds of the last trade / update
    bid: Optional[float] = None
    ask: Optional[float] = None

    @property
    def change(self) -> Optional[float]:
        return None if not self.reference else self.price - self.reference

    @property
    def change_pct(self) -> Optional[float]:
        return None if not self.reference else (self.price / self.reference - 1) * 100


_STOCK_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
_CRYPTO_RE = re.compile(r"^[A-Z0-9]{2,10}-[A-Z]{3,5}$")


def normalize(symbol: str, kind: str) -> str:
    """User input → provider symbol: ' aapl ' → AAPL; btc, btc/usd, btcusd → BTC-USD; gold, xau/usd → XAU."""
    s = symbol.strip().upper().replace(" ", "")
    if kind == STOCK:
        return s
    if kind == METAL:
        s = s.replace("/USD", "").replace("-USD", "").replace("USD", "") if s not in _METAL_WORDS else s
        return _METAL_WORDS.get(s, s)
    s = s.replace("/", "-").replace("_", "-")
    if "-" not in s:
        for quote in ("USDC", "USDT", "USD", "EUR", "GBP"):
            if s.endswith(quote) and len(s) > len(quote):
                return f"{s[:-len(quote)]}-{quote}"
        return f"{s}-USD"
    return s


def valid_format(symbol: str, kind: str) -> bool:
    if kind == METAL:
        return symbol in METALS
    return bool((_STOCK_RE if kind == STOCK else _CRYPTO_RE).match(symbol))
