"""US stock market session: open, pre-market, after hours or closed.

Uses Alpaca's clock (holidays included) and today's calendar entry (early
closes) when keys are set; otherwise a plain Mon–Fri 9:30–16:00 ET rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PRE_START, POST_END = time(4, 0), time(20, 0)
OPEN, PRE, POST, CLOSED = "open", "pre", "post", "closed"


@dataclass
class Market:
    is_open: bool
    next_open: Optional[datetime] = None
    next_close: Optional[datetime] = None
    today_open: Optional[datetime] = None      # today's regular session, if today trades
    today_close: Optional[datetime] = None
    pre_start: Optional[datetime] = None       # today's extended session bounds
    post_end: Optional[datetime] = None
    estimated: bool = False                    # no Alpaca clock: weekday rule, no holidays

    def session(self, now: datetime) -> str:
        if self.is_open:
            return OPEN
        t = now.astimezone(ET)
        if self.today_open and self.pre_start and self.pre_start <= t < self.today_open:
            return PRE
        if self.today_close and self.post_end and self.today_close <= t < self.post_end:
            return POST
        return CLOSED

    def label(self, now: Optional[datetime] = None) -> str:
        now = now or datetime.now(ET)
        s = self.session(now)
        if s == OPEN:
            text = f"Market open · closes {_when(self.next_close, now)}"
        else:
            text = {PRE: "Pre-market", POST: "After hours", CLOSED: "Market closed"}[s]
            if self.next_open:
                text += f" · opens {_when(self.next_open, now)}"
        return text + (" (est.)" if self.estimated else "")


def _when(dt: Optional[datetime], now: datetime) -> str:
    if dt is None:
        return "?"
    d = dt.astimezone(ET)
    hm = d.strftime("%I:%M %p").lstrip("0") + " ET"
    today = now.astimezone(ET).date()
    if d.date() == today:
        return hm
    if (d.date() - today).days < 7:
        return f"{d.strftime('%a')} {hm}"
    return f"{d.strftime('%b')} {d.day} {hm}"


def _dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if "." in s:                                   # trim nanoseconds
        head, rest = s.split(".", 1)
        i = next((k for k, ch in enumerate(rest) if not ch.isdigit()), len(rest))
        s = f"{head}.{rest[:i][:6]}{rest[i:]}"
    return datetime.fromisoformat(s)


def from_alpaca(clock: dict, calendar: Optional[list] = None, today: Optional[date] = None) -> Market:
    """Alpaca /v2/clock and /v2/calendar?start=today&end=today responses → Market."""
    m = Market(bool(clock.get("is_open")), _dt(clock.get("next_open")), _dt(clock.get("next_close")))
    today = today or datetime.now(ET).date()
    for day in calendar or []:
        if day.get("date") == today.isoformat():
            hhmm = lambda v: time.fromisoformat(v if len(v) > 4 else f"{v[:2]}:{v[2:]}")
            m.today_open = datetime.combine(today, hhmm(day["open"]), ET)
            m.today_close = datetime.combine(today, hhmm(day["close"]), ET)
            m.pre_start = datetime.combine(today, hhmm(day.get("session_open") or "04:00"), ET)
            m.post_end = datetime.combine(today, hhmm(day.get("session_close") or "20:00"), ET)
    return m


def estimate(now: Optional[datetime] = None) -> Market:
    """Weekday 9:30–16:00 ET rule, for when there's no Alpaca clock (no holidays)."""
    from datetime import timedelta
    t = (now or datetime.now(ET)).astimezone(ET)
    def session(d: date):
        return datetime.combine(d, time(9, 30), ET), datetime.combine(d, time(16, 0), ET)
    today = session(t.date()) if t.weekday() < 5 else (None, None)
    is_open = bool(today[0] and today[0] <= t < today[1])
    d = t.date() if (today[0] and t < today[0]) else t.date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    nxt_close = today[1] if is_open else session(d)[1]
    pre = datetime.combine(t.date(), PRE_START, ET) if today[0] else None
    post = datetime.combine(t.date(), POST_END, ET) if today[0] else None
    return Market(is_open, session(d)[0], nxt_close, today[0], today[1], pre, post, estimated=True)
