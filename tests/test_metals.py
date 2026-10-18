from datetime import datetime

from ticker import market as m
from ticker.db import Store
from ticker.models import METAL, Entry, normalize, valid_format
from ticker.providers import metals

ET = m.ET


def at(*a):
    return datetime(*a, tzinfo=ET)


def test_normalize_metals():
    for raw, sym in (("gold", "XAU"), (" Silver ", "XAG"), ("xau/usd", "XAU"), ("XAGUSD", "XAG"),
                     ("platinum", "XPT"), ("XPD", "XPD")):
        assert normalize(raw, METAL) == sym and valid_format(sym, METAL)
    assert not valid_format(normalize("copper", METAL), METAL)


def test_metals_hours():
    assert not m.metals_open(at(2026, 10, 17, 12))           # Saturday
    assert not m.metals_open(at(2026, 10, 18, 17, 59))       # Sunday before 6 PM
    assert m.metals_open(at(2026, 10, 18, 18, 0))            # Sunday open
    assert not m.metals_open(at(2026, 10, 19, 17, 30))       # Monday daily break
    assert m.metals_open(at(2026, 10, 19, 18, 1))
    assert not m.metals_open(at(2026, 10, 23, 17, 0))        # Friday close
    assert m.next_metal_open(at(2026, 10, 17, 12)) == at(2026, 10, 18, 18)
    assert m.metals_label(at(2026, 10, 17, 12)) == "Metals closed · opens Sun 6:00 PM ET"


def test_reference_close():
    # trading Tuesday 10 AM → Monday's 5 PM close
    assert m.metal_reference_close(at(2026, 10, 20, 10)) == at(2026, 10, 19, 17)
    # weekend: shown price is Friday's close → change vs Thursday's close
    assert m.metal_reference_close(at(2026, 10, 18, 12)) == at(2026, 10, 15, 17)
    # Sunday evening session (Monday's) → Friday's close
    assert m.metal_reference_close(at(2026, 10, 18, 19)) == at(2026, 10, 16, 17)
    # daily break Monday 5:30 PM → shown price is Monday's close → vs Friday
    assert m.metal_reference_close(at(2026, 10, 19, 17, 30)) == at(2026, 10, 16, 17)


FEED = [{"topo": {"platform": "AT"}, "spreadProfilePrices": [{"spreadProfile": "standard", "bid": 1.0, "ask": 3.0}],
         "ts": 1000},
        {"topo": {"platform": "SwissquoteLtd"}, "ts": 1792184400073,
         "spreadProfilePrices": [{"spreadProfile": "premium", "bid": 4163.9, "ask": 4164.8},
                                 {"spreadProfile": "prime", "bid": 4164.0, "ask": 4164.8}]}]


def test_parse_bbo():
    mid, bid, ask, ts = metals.parse_bbo(FEED)
    assert (bid, ask, round(mid, 2), ts) == (4164.0, 4164.8, 4164.4, 1792184400.073)
    assert metals.parse_bbo(FEED[:1])[0] == 2.0                # no Swissquote platform: first usable
    assert metals.parse_bbo([]) is None


def test_tick_store_reference_and_trend(tmp_path):
    path = tmp_path / "w.db"
    Store(path).close()                                        # creates both tables (v2)
    ts = metals.TickStore(str(path))
    thu = at(2026, 10, 15, 17).timestamp()
    ts.record("XAU", thu - 600, 4100.0)
    ts.record("XAU", thu - 100, 4110.0)                        # same 5-min bucket? no: different
    ts.record("XAU", thu + 3600, 4120.0)
    ts.record("XAU", at(2026, 10, 16, 16, 58).timestamp(), 4164.0)
    assert ts.price_at("XAU", at(2026, 10, 15, 17)) == 4110.0
    assert ts.price_at("XAU", at(2026, 10, 14, 17)) is None   # app wasn't running then
    p = metals.MetalsProvider(lambda q: None, lambda s: None, str(path))
    p._store = ts
    sat = at(2026, 10, 17, 12)
    q = p.quote("XAU", 4164.0, 4163.9, 4164.1, 0, sat)
    assert q.reference == 4110.0 and round(q.change, 1) == 54.0
    assert p.trend("XAU", sat) == [4120.0, 4164.0]           # 24 h before Friday's close
    ts.record("XAU", thu - 50, 4111.0)                        # same bucket as thu-100: replaced
    assert ts.price_at("XAU", at(2026, 10, 15, 17)) == 4111.0
    ts.close()


def test_metal_entry_round_trip(tmp_path):
    s = Store(tmp_path / "x.db")
    e = s.add(Entry(None, "XAU", METAL, "Gold"))
    assert s.get(e.id).kind == METAL
    s.close()
