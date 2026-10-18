from ticker import format as fmt
from ticker.models import CRYPTO, STOCK, Entry, Quote, normalize, valid_format


def test_normalize_and_validate():
    assert normalize(" aapl ", STOCK) == "AAPL"
    assert normalize("btc", CRYPTO) == "BTC-USD"
    assert normalize("eth/usd", CRYPTO) == "ETH-USD"
    assert normalize("solusdc", CRYPTO) == "SOL-USDC"
    assert normalize("pepe-usd", CRYPTO) == "PEPE-USD"
    assert valid_format("BRK.B", STOCK) and not valid_format("BTC-USD", STOCK)
    assert valid_format("BTC-USD", CRYPTO) and not valid_format("BTC", CRYPTO)


def test_quote_change():
    q = Quote("AAPL", STOCK, 110.0, 100.0)
    assert q.change == 10 and round(q.change_pct, 6) == 10
    assert Quote("X", STOCK, 1.0).change_pct is None


def test_formatting():
    assert fmt.price(81878.41) == "81,878.41"
    assert fmt.price(0.5123) == "0.5123"
    assert fmt.price(0.000004123) == "0.000004123"
    assert fmt.price(None) == "—"
    assert fmt.change(-0.00000004, like=0.0000039) == "−0.000000040"
    assert fmt.change(456.54, like=81838.33) == "+456.54"
    assert fmt.change(-1.5) == "−1.50" and fmt.pct(2.345) == "+2.35%"
    assert fmt.age(1000, now=1003) == "3s" and fmt.age(0) == "—"
    assert fmt.age(0.5, now=7200.5) == "2h"


def _tracker():
    now = {"t": 1000.0}
    return fmt.AlertTracker(clock=lambda: now["t"]), now


def test_alert_fires_once_then_waits_while_price_bounces():
    t, now = _tracker()
    e = Entry(1, "BTC-USD", CRYPTO, alert_above=100, alert_below=50)
    assert t.check(e, 99) == []
    [a] = t.check(e, 101)
    assert a.side == "above" and "BTC-USD is above" in a.text() and "now 101.00" in a.text()
    for p in (99, 102, 98, 103, 97, 104):                       # bouncing around the level: no new alerts
        now["t"] += 10
        assert t.check(e, p) == []
    a = t.pending[(1, "above")]
    assert a.hits == 4 and a.price == 104 and a.last_at == 1060
    assert [x.side for x in t.check(e, 49)] == ["below"]         # the other side is its own alert


def test_snooze_silences_then_fires_again_if_still_past():
    t, now = _tracker()
    e = Entry(1, "BTC-USD", CRYPTO, alert_above=100)
    t.check(e, 101)
    t.snooze((1, "above"), 15)
    assert (1, "above") not in t.pending and t.snoozed_until((1, "above")) == 1000 + 900
    for p in (99, 101, 98, 105):
        now["t"] += 60
        assert t.check(e, p) == []                               # silent for 15 minutes
    now["t"] = 1000 + 901
    assert len(t.check(e, 106)) == 1                             # still above after the snooze: one reminder
    assert t.snoozed_until((1, "above")) is None


def test_snooze_expired_and_price_back_under_waits_for_next_cross():
    t, now = _tracker()
    e = Entry(1, "BTC-USD", CRYPTO, alert_above=100)
    t.check(e, 101)
    t.snooze((1, "above"), 5)
    now["t"] += 301
    assert t.check(e, 95) == [] and len(t.check(e, 100)) == 1


def test_without_snooze_rearms_after_crossing_back():
    t, now = _tracker()
    e = Entry(1, "BTC-USD", CRYPTO, alert_above=100)
    t.check(e, 101)
    t.pending.clear()                                            # e.g. the alert window was closed elsewhere
    assert t.check(e, 105) == []                                 # still above: no repeat
    assert t.check(e, 95) == [] and len(t.check(e, 100)) == 1


def test_turn_off_and_edited_level():
    t, now = _tracker()
    e = Entry(1, "BTC-USD", CRYPTO, alert_above=100)
    t.check(e, 101)
    e.alert_above = None                                         # "Turn off alert" clears the level
    assert t.check(e, 120) == [] and t.pending == {}
    e.alert_above = 110
    assert len(t.check(e, 120)) == 1                             # a new level is a new alert
    e.alert_above = 115
    assert len(t.check(e, 120)) == 1 and t.pending[(1, "above")].level == 115
    t.forget(1)
    assert t.pending == {} and t.snoozed_until((1, "above")) is None
