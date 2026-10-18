"""Number formatting and price-alert checks (no Qt, so they're easy to test)."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
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


@dataclass
class Alert:
    """One alert level that was hit and is waiting to be acknowledged."""
    entry_id: int
    symbol: str
    side: str                 # "above" | "below"
    level: float
    price: float              # latest price
    first_at: float
    last_at: float
    hits: int = 1             # times it crossed the level while waiting

    @property
    def key(self) -> tuple[int, str]:
        return self.entry_id, self.side

    def text(self) -> str:
        return f"{self.symbol} is {self.side} {price(self.level)} (now {price(self.price, like=self.level)})"


class AlertTracker:
    """Price alerts that don't nag.

    An alert fires when the price reaches its level, then waits for you
    (``pending``). While it waits, more crossings only update its price and hit
    count — no new notification however much the price bounces. Acknowledge it
    with ``snooze(key, minutes)`` (silent for that long; afterwards it fires
    again if the price is still past the level or crosses it again) or turn the
    alert off (the caller clears the level; ``forget`` drops its state).
    Without a snooze it re-arms only after the price crosses back.
    """

    def __init__(self, clock=time.time):
        self.clock = clock
        self.pending: dict[tuple[int, str], Alert] = {}
        self._fired: set[tuple[int, str]] = set()          # hit and not crossed back yet
        self._snoozed: dict[tuple[int, str], float] = {}  # key → silent until (epoch s)

    def check(self, e: Entry, p: float) -> list[Alert]:
        """New alerts to notify about (already-pending ones are updated silently)."""
        now, out = self.clock(), []
        for side, level in (("above", e.alert_above), ("below", e.alert_below)):
            key = (e.id, side)
            if level is None:
                self._drop(key)
                continue
            hit = p >= level if side == "above" else p <= level
            if key in self.pending:
                a = self.pending[key]
                if a.level != level:                       # level edited while waiting: a new alert
                    del self.pending[key]
                    self._fired.discard(key)
                else:
                    if hit and key not in self._fired:
                        a.hits += 1
                        a.last_at = now
                    a.price = p
                    self._set_fired(key, hit)
                    continue
            if self._snoozed.get(key, 0) > now:            # silent; when it ends, fires if still past
                continue
            self._snoozed.pop(key, None)
            if hit and key not in self._fired:
                a = Alert(e.id, e.symbol, side, level, p, now, now)
                self.pending[key] = a
                out.append(a)
            self._set_fired(key, hit)
        return out

    def _set_fired(self, key, hit: bool) -> None:
        (self._fired.add if hit else self._fired.discard)(key)

    def snooze(self, key: tuple[int, str], minutes: float) -> None:
        """Acknowledge: silent for ``minutes``, then it may fire again (even if still past the level)."""
        self.pending.pop(key, None)
        self._snoozed[key] = self.clock() + minutes * 60
        self._fired.discard(key)

    def snoozed_until(self, key: tuple[int, str]) -> Optional[float]:
        t = self._snoozed.get(key)
        return t if t and t > self.clock() else None

    def _drop(self, key) -> None:
        self.pending.pop(key, None)
        self._fired.discard(key)
        self._snoozed.pop(key, None)

    def forget(self, entry_id: int) -> None:
        for key in [k for k in {*self.pending, *self._fired, *self._snoozed} if k[0] == entry_id]:
            self._drop(key)
