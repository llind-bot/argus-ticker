"""Number formatting and price-alert checks (no Qt, so they're easy to test)."""

from __future__ import annotations

import math
import time
from typing import Optional

from .models import Entry


def decimals(p: float) -> int:
    """2 from $1 up; small coins keep 4 significant digits (0.000004123 → 9)."""
    return 2 if abs(p) >= 1 or p == 0 else -math.floor(math.log10(abs(p))) + 3


def price(p: Optional[float], like: Optional[float] = None) -> str:
    """Price with thousands separators; ``like``: use that price's decimals instead."""
    if p is None:
        return "—"
    return f"{p:,.{decimals(p if like is None else like)}f}"


def change(c: Optional[float], like: Optional[float] = None) -> str:
    """Signed change, shown with the decimals of the price it belongs to (``like``)."""
    if c is None:
        return "—"
    return ("+" if c > 0 else "−" if c < 0 else "") + price(abs(c), like)


def pct(p: Optional[float]) -> str:
    if p is None:
        return "—"
    return ("+" if p > 0 else "−" if p < 0 else "") + f"{abs(p):.2f}%"


def age(ts: float, now: Optional[float] = None) -> str:
    """Time since the last update: '3s', '4m', '2h', '3d'."""
    if not ts:
        return "—"
    s = max(0, (now or time.time()) - ts)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{int(s // size)}{unit}"
    return f"{int(s)}s"


class AlertTracker:
    """Fires once when a price crosses an entry's alert level; re-arms when it crosses back."""

    def __init__(self):
        self._fired: set[tuple[int, str]] = set()

    def check(self, e: Entry, p: float) -> list[str]:
        out = []
        for side, level, hit in (("above", e.alert_above, lambda: p >= e.alert_above),
                                 ("below", e.alert_below, lambda: p <= e.alert_below)):
            key = (e.id, side)
            if level is None:
                self._fired.discard(key)
            elif hit():
                if key not in self._fired:
                    self._fired.add(key)
                    out.append(f"{e.symbol} is {side} {price(level)} (now {price(p)})")
            else:
                self._fired.discard(key)
        return out

    def forget(self, entry_id: int) -> None:
        self._fired = {k for k in self._fired if k[0] != entry_id}
