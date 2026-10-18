import json

import pytest

from ticker import transfer
from ticker.db import Store
from ticker.models import CRYPTO, STOCK, Entry


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add(Entry(None, "AAPL", STOCK, "Apple", "long, \"core\"", 400.0, None))
    s.add(Entry(None, "BTC-USD", CRYPTO, alert_below=70000))
    yield s
    s.close()


@pytest.mark.parametrize("ext", ["json", "csv"])
def test_round_trip(store, tmp_path, ext):
    path = tmp_path / f"w.{ext}"
    transfer.export_entries(store.list(), path)
    entries, problems = transfer.read_entries(path)
    assert problems == []
    assert [(e.symbol, e.kind, e.name, e.notes, e.alert_above, e.alert_below) for e in entries] == [
        ("AAPL", STOCK, "Apple", 'long, "core"', 400.0, None), ("BTC-USD", CRYPTO, "", "", None, 70000.0)]
    other = Store(tmp_path / f"other_{ext}.db")
    other.add(Entry(None, "AAPL", STOCK))
    assert transfer.import_entries(other, entries) == (1, ["AAPL"])
    assert [e.symbol for e in other.list()] == ["AAPL", "BTC-USD"]
    other.close()


def test_hand_written_csv_and_bad_rows(tmp_path):
    path = tmp_path / "mine.csv"
    path.write_text("Symbol,Kind,Alert_Above\n msft ,Stock,$500\neth,crypto,\nXYZ,bond,\nNVDA,stock,abc\n",
                    encoding="utf-8")
    entries, problems = transfer.read_entries(path)
    assert [(e.symbol, e.alert_above) for e in entries] == [("MSFT", 500.0), ("ETH-USD", None)]
    assert len(problems) == 2 and "row 3" in problems[0] and "row 4" in problems[1]


def test_json_plain_list(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([{"symbol": "sol", "kind": "crypto"}]), encoding="utf-8")
    assert transfer.read_entries(path)[0][0].symbol == "SOL-USD"
