from datetime import date, datetime

from ticker import market as m
from ticker import updates

ET = m.ET
CLOCK = {"is_open": False, "next_open": "2026-10-19T09:30:00-04:00", "next_close": "2026-10-19T16:00:00-04:00"}
CAL = [{"date": "2026-10-19", "open": "09:30", "close": "16:00", "session_open": "0400", "session_close": "2000"}]


def at(*a):
    return datetime(*a, tzinfo=ET)


def test_weekend_closed():
    mk = m.from_alpaca(CLOCK, [], today=date(2026, 10, 18))
    now = at(2026, 10, 18, 12, 0)
    assert mk.session(now) == m.CLOSED
    assert mk.label(now) == "Market closed · opens Mon 9:30 AM ET"


def test_pre_open_post():
    day = date(2026, 10, 19)
    mk = m.from_alpaca(CLOCK, CAL, today=day)
    assert mk.session(at(2026, 10, 19, 3, 59)) == m.CLOSED
    assert mk.session(at(2026, 10, 19, 8, 0)) == m.PRE
    assert mk.label(at(2026, 10, 19, 8, 0)) == "Pre-market · opens 9:30 AM ET"
    opened = m.from_alpaca({**CLOCK, "is_open": True}, CAL, today=day)
    assert opened.label(at(2026, 10, 19, 10, 0)) == "Market open · closes 4:00 PM ET"
    after = m.from_alpaca({**CLOCK, "next_open": "2026-10-20T09:30:00-04:00"}, CAL, today=day)
    assert after.session(at(2026, 10, 19, 17, 0)) == m.POST
    assert after.session(at(2026, 10, 19, 20, 0)) == m.CLOSED


def test_early_close_day():
    cal = [{"date": "2026-11-27", "open": "09:30", "close": "13:00", "session_open": "0400", "session_close": "1700"}]
    mk = m.from_alpaca({"is_open": False, "next_open": "2026-11-30T09:30:00-05:00"}, cal, today=date(2026, 11, 27))
    assert mk.session(at(2026, 11, 27, 14, 0)) == m.POST
    assert mk.session(at(2026, 11, 27, 17, 30)) == m.CLOSED


def test_estimate_without_keys():
    assert m.estimate(at(2026, 10, 19, 10, 0)).is_open                      # Monday
    sat = m.estimate(at(2026, 10, 17, 10, 0))
    assert not sat.is_open and sat.next_open == at(2026, 10, 19, 9, 30)
    fri_eve = m.estimate(at(2026, 10, 16, 18, 0))
    assert fri_eve.session(at(2026, 10, 16, 18, 0)) == m.POST and fri_eve.next_open == at(2026, 10, 19, 9, 30)
    assert sat.label(at(2026, 10, 17, 10, 0)).endswith("(est.)")


def test_update_versions(monkeypatch):
    assert updates.parse_version("v0.10.1") > updates.parse_version("0.9.9")
    monkeypatch.setattr(updates, "http_get_json", lambda *a, **k: {"tag_name": "v0.3.0", "html_url": "u"})
    info = updates.check("0.2.0")
    assert info.newer and info.latest == "0.3.0" and info.url == "u"
    assert not updates.check("0.3.0").newer

    def boom(*a, **k):
        raise updates.HttpError(404)
    monkeypatch.setattr(updates, "http_get_json", boom)
    assert updates.check() is None
