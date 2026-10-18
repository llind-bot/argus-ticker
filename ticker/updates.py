"""'Update available' check against the GitHub releases of the app's repo.

Only works while the releases are publicly visible; for a private repo
GitHub answers 404 and the check reports that it couldn't look.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import __version__
from .providers.base import HttpError, http_get_json

REPO = "llind-bot/argus-ticker"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"


def parse_version(s: str) -> tuple[int, ...]:
    m = re.match(r"v?(\d+(?:\.\d+)*)", s.strip())
    return tuple(int(x) for x in m[1].split(".")) if m else ()


@dataclass
class UpdateInfo:
    latest: str
    url: str
    newer: bool


def check(current: str = __version__) -> Optional[UpdateInfo]:
    """Latest release vs ``current``; None if GitHub can't be asked (offline, private repo)."""
    try:
        rel = http_get_json(LATEST_URL, {"Accept": "application/vnd.github+json"}, timeout=8)
    except (HttpError, OSError):
        return None
    tag = rel.get("tag_name") or ""
    url = rel.get("html_url") or RELEASES_PAGE
    return UpdateInfo(tag.lstrip("v"), url, parse_version(tag) > parse_version(current))
