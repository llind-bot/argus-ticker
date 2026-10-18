"""Shared helpers for quote providers.

A provider runs inside the quote service's asyncio loop: ``run()`` loops
until cancelled, calling ``emit(quote)`` for every update and
``status(text)`` for connection changes. ``set_symbols()`` is called from
the same loop whenever the watchlist changes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable, Optional

from ..models import Quote

Emit = Callable[[Quote], None]
Status = Callable[[str], None]
USER_AGENT = "ArgusTicker/0.1"


class HttpError(Exception):
    def __init__(self, code: int, body: str = ""):
        super().__init__(f"HTTP {code}")
        self.code, self.body = code, body


def http_get_json(url: str, headers: Optional[dict] = None, timeout: float = 10) -> Any:
    """Blocking GET → parsed JSON (run it with asyncio.to_thread)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read(300).decode("utf-8", "replace")) from None


def parse_time(iso: Optional[str]) -> float:
    """RFC 3339 with up to nanoseconds ('2026-10-16T19:59:58.574873201Z') → epoch s."""
    if not iso:
        return 0.0
    s = iso.replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        i = next((k for k, ch in enumerate(rest) if not ch.isdigit()), len(rest))
        s = f"{head}.{rest[:i][:6]}{rest[i:]}"
    return datetime.fromisoformat(s).timestamp()


def as_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
