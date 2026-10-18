"""App settings: preferences in QSettings, Alpaca keys in the OS keychain.

On Windows ``keyring`` stores the keys in Credential Manager (macOS:
Keychain). ALPACA_API_KEY / ALPACA_SECRET_KEY environment variables, when
set, take precedence — handy for development.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QSettings

SERVICE = "ArgusTicker"
_log = logging.getLogger("ticker.settings")


@dataclass
class Prefs:
    feed: str = "iex"
    interval: float = 5.0
    always_on_top: bool = False


def load_prefs() -> Prefs:
    s = QSettings()
    return Prefs(feed=str(s.value("alpaca/feed", "iex")),
                 interval=float(s.value("alpaca/interval", 5.0)),
                 always_on_top=s.value("ui/always_on_top", False, type=bool))


def save_prefs(p: Prefs) -> None:
    s = QSettings()
    s.setValue("alpaca/feed", p.feed)
    s.setValue("alpaca/interval", p.interval)
    s.setValue("ui/always_on_top", p.always_on_top)


def _keyring():
    try:
        import keyring
        return keyring
    except Exception as e:                               # noqa: BLE001 — no backend: env vars only
        _log.warning("keyring unavailable: %s", e)
        return None


def keys_from_env() -> bool:
    return bool(os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY"))


def load_keys() -> tuple[Optional[str], Optional[str]]:
    if keys_from_env():
        return os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    kr = _keyring()
    if kr is None:
        return None, None
    try:
        return kr.get_password(SERVICE, "alpaca_key"), kr.get_password(SERVICE, "alpaca_secret")
    except Exception as e:                               # noqa: BLE001
        _log.warning("reading keys failed: %s", e)
        return None, None


def save_keys(key: str, secret: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError("No system keychain available to store the keys")
    if key and secret:
        kr.set_password(SERVICE, "alpaca_key", key)
        kr.set_password(SERVICE, "alpaca_secret", secret)
    else:
        for name in ("alpaca_key", "alpaca_secret"):
            try:
                kr.delete_password(SERVICE, name)
            except Exception:                            # noqa: BLE001 — nothing stored
                pass
