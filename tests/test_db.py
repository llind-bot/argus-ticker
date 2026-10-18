import pytest

from ticker.db import DuplicateEntry, Store
from ticker.models import CRYPTO, STOCK, Entry


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_crud(store):
    a = store.add(Entry(None, "AAPL", STOCK, "Apple"))
    b = store.add(Entry(None, "BTC-USD", CRYPTO, alert_above=100000))
    assert [e.symbol for e in store.list()] == ["AAPL", "BTC-USD"]
    assert b.alert_above == 100000 and b.alert_below is None
    a.name, a.notes, a.alert_below = "Apple Inc.", "long term", 200.5
    assert store.update(a).name == "Apple Inc." and store.get(a.id).alert_below == 200.5
    store.delete(a.id)
    assert [e.symbol for e in store.list()] == ["BTC-USD"] and store.get(a.id) is None


def test_duplicates_rejected_but_same_symbol_other_kind_ok(store):
    store.add(Entry(None, "AAPL", STOCK))
    with pytest.raises(DuplicateEntry):
        store.add(Entry(None, "AAPL", STOCK))
    x = store.add(Entry(None, "ETH-USD", CRYPTO))
    x.symbol = "AAPL"
    x.kind = STOCK
    with pytest.raises(DuplicateEntry):
        store.update(x)


def test_move(store):
    ids = [store.add(Entry(None, s, STOCK)).id for s in ("A", "B", "C")]
    store.move(ids[2], -1)
    assert [e.symbol for e in store.list()] == ["A", "C", "B"]
    store.move(ids[0], 5)                                  # clamps at the end
    assert [e.symbol for e in store.list()] == ["C", "B", "A"]
    store.move(ids[2], -9)
    assert [e.symbol for e in store.list()] == ["C", "B", "A"]  # C already first
    assert store.add(Entry(None, "D", STOCK)).sort == 3    # new entries go last
