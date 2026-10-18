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


def test_alerts_fire_once_and_rearm():
    t = fmt.AlertTracker()
    e = Entry(1, "BTC-USD", CRYPTO, alert_above=100, alert_below=50)
    assert t.check(e, 99) == []
    assert len(t.check(e, 101)) == 1
    assert t.check(e, 105) == []                    # still above: no repeat
    assert t.check(e, 95) == []                     # back under: re-armed
    assert "above" in t.check(e, 100)[0]
    assert "below" in t.check(e, 49)[0]
