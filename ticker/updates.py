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


EXE_NAME = "ArgusTicker.exe"


@dataclass
class UpdateInfo:
    latest: str
    url: str                                   # release page
    newer: bool
    exe_url: Optional[str] = None              # direct download of ArgusTicker.exe
    sha256: Optional[str] = None               # GitHub's digest of it, when reported
    sha_url: Optional[str] = None              # ArgusTicker.exe.sha256 published with the release

    @property
    def installable(self) -> bool:
        return bool(self.exe_url and (self.sha256 or self.sha_url))


def check(current: str = __version__) -> Optional[UpdateInfo]:
    """Latest release vs ``current``; None if GitHub can't be asked (offline, private repo)."""
    try:
        rel = http_get_json(LATEST_URL, {"Accept": "application/vnd.github+json"}, timeout=8)
    except (HttpError, OSError):
        return None
    return parse_release(rel, current)


def parse_release(rel: dict, current: str = __version__) -> UpdateInfo:
    tag = rel.get("tag_name") or ""
    info = UpdateInfo(tag.lstrip("v"), rel.get("html_url") or RELEASES_PAGE,
                      parse_version(tag) > parse_version(current))
    for a in rel.get("assets") or []:
        if a.get("name") == EXE_NAME:
            info.exe_url = a.get("browser_download_url")
            digest = a.get("digest") or ""
            if digest.startswith("sha256:"):
                info.sha256 = digest.split(":", 1)[1].lower()
        elif a.get("name") == EXE_NAME + ".sha256":
            info.sha_url = a.get("browser_download_url")
    return info
