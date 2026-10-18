"""Watchlist export / import as JSON or CSV (by file extension)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

from . import __version__
from .db import DuplicateEntry, Store
from .models import KINDS, Entry, normalize, valid_format

FIELDS = ["symbol", "kind", "name", "notes", "alert_above", "alert_below"]


def export_entries(entries: list[Entry], path: Path | str) -> None:
    path = Path(path)
    rows = [{f: getattr(e, f) for f in FIELDS} for e in entries]
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, FIELDS)
            w.writeheader()
            w.writerows({k: ("" if v is None else v) for k, v in r.items()} for r in rows)
    else:
        path.write_text(json.dumps({"app": "ArgusTicker", "version": __version__, "entries": rows}, indent=2),
                        encoding="utf-8")


def _opt_float(v) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return float(str(v).replace(",", "").lstrip("$"))


def read_entries(path: Path | str) -> tuple[list[Entry], list[str]]:
    """Entries from a file, plus a message for each row that couldn't be used."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    else:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = data.get("entries", []) if isinstance(data, dict) else data
    entries, problems = [], []
    for n, r in enumerate(rows, 1):
        r = {str(k).strip().lower(): v for k, v in (r or {}).items() if k is not None}
        kind = str(r.get("kind") or "").strip().lower()
        if kind not in KINDS:
            problems.append(f"row {n}: type must be 'stock' or 'crypto' (got {r.get('kind')!r})")
            continue
        sym = normalize(str(r.get("symbol") or ""), kind)
        if not valid_format(sym, kind):
            problems.append(f"row {n}: bad symbol {r.get('symbol')!r}")
            continue
        try:
            above, below = _opt_float(r.get("alert_above")), _opt_float(r.get("alert_below"))
        except ValueError:
            problems.append(f"row {n}: {sym} alert levels must be numbers")
            continue
        entries.append(Entry(None, sym, kind, str(r.get("name") or "").strip(), str(r.get("notes") or "").strip(),
                             above, below))
    return entries, problems


def import_entries(store: Store, entries: list[Entry]) -> tuple[int, list[str]]:
    """Add entries not already in the list; returns (added, symbols skipped as duplicates)."""
    added, skipped = 0, []
    for e in entries:
        try:
            store.add(e)
            added += 1
        except DuplicateEntry:
            skipped.append(e.symbol)
    return added, skipped
