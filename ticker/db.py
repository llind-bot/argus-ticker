"""Watchlist store (SQLite)."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from .models import KINDS, Entry

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    alert_above REAL,
    alert_below REAL,
    sort INTEGER NOT NULL DEFAULT 0,
    UNIQUE (symbol, kind));
"""
_COLS = "id, symbol, kind, name, notes, alert_above, alert_below, sort"


def default_path() -> Path:
    """%APPDATA%\\ArgusTicker\\ticker.db on Windows, ~/.argus-ticker/ticker.db elsewhere."""
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "ArgusTicker"
    else:
        base = Path.home() / ".argus-ticker"
    base.mkdir(parents=True, exist_ok=True)
    return base / "ticker.db"


class DuplicateEntry(ValueError):
    pass


class Store:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def list(self) -> list[Entry]:
        rows = self.conn.execute(f"SELECT {_COLS} FROM entries ORDER BY sort, id").fetchall()
        return [Entry(*r) for r in rows]

    def get(self, entry_id: int) -> Optional[Entry]:
        r = self.conn.execute(f"SELECT {_COLS} FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return Entry(*r) if r else None

    def add(self, e: Entry) -> Entry:
        if e.kind not in KINDS:
            raise ValueError(f"unknown kind {e.kind!r}")
        sort = self.conn.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM entries").fetchone()[0]
        try:
            cur = self.conn.execute(
                "INSERT INTO entries (symbol, kind, name, notes, alert_above, alert_below, sort) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (e.symbol, e.kind, e.name, e.notes, e.alert_above, e.alert_below, sort))
        except sqlite3.IntegrityError:
            raise DuplicateEntry(f"{e.symbol} is already in the list") from None
        self.conn.commit()
        return self.get(cur.lastrowid)

    def update(self, e: Entry) -> Entry:
        try:
            self.conn.execute(
                "UPDATE entries SET symbol = ?, kind = ?, name = ?, notes = ?, alert_above = ?, "
                "alert_below = ? WHERE id = ?",
                (e.symbol, e.kind, e.name, e.notes, e.alert_above, e.alert_below, e.id))
        except sqlite3.IntegrityError:
            raise DuplicateEntry(f"{e.symbol} is already in the list") from None
        self.conn.commit()
        return self.get(e.id)

    def delete(self, entry_id: int) -> None:
        self.conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self.conn.commit()

    def move(self, entry_id: int, delta: int) -> None:
        """Move an entry up (delta < 0) or down in the list."""
        ids = [e.id for e in self.list()]
        i = ids.index(entry_id)
        j = max(0, min(len(ids) - 1, i + delta))
        ids.insert(j, ids.pop(i))
        self.conn.executemany("UPDATE entries SET sort = ? WHERE id = ?", [(k, x) for k, x in enumerate(ids)])
        self.conn.commit()
