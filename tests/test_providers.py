import asyncio

from ticker.models import CRYPTO, STOCK
from ticker.providers import alpaca, coinbase
from ticker.providers.base import parse_time


def test_parse_time_nanoseconds():
    assert parse_time("2026-10-16T19:59:58.574873201Z") == parse_time("2026-10-16T19:59:58.574873Z")
    assert parse_time("2026-10-16T20:00:00Z") - parse_time("2026-10-16T19:59:58.5Z") == 1.5
    assert parse_time(None) == 0.0


def test_coinbase_ticker_and_stats():
    q = coinbase.parse_ticker({"type": "ticker", "product_id": "BTC-USD", "price": "81878.41",
                               "open_24h": "81408.28", "best_bid": "81878.40", "best_ask": "81878.42",
                               "time": "2026-10-18T15:00:00.123456Z"})
    assert (q.symbol, q.kind, q.price, q.reference, q.bid) == ("BTC-USD", CRYPTO, 81878.41, 81408.28, 81878.40)
    assert coinbase.parse_ticker({"type": "subscriptions"}) is None
    s = coinbase.parse_stats("ETH-USD", {"open": "3000", "last": "3150.5"})
    assert s.price == 3150.5 and round(s.change_pct, 2) == 5.02
    assert coinbase.parse_stats("ETH-USD", {}) is None


SNAP = {
    "AAPL": {"latestTrade": {"p": 343.39, "t": "2026-10-16T19:59:58.574873201Z"},
             "latestQuote": {"bp": 343.3, "ap": 343.5}, "prevDailyBar": {"c": 341.91},
             "dailyBar": {"c": 343.39}},
    "NOTRADE": {"dailyBar": {"c": 10.0}, "prevDailyBar": {"c": 9.0}},
    "EMPTY": None,
}


def test_alpaca_snapshots():
    quotes = {q.symbol: q for q in alpaca.parse_snapshots(SNAP)}
    a = quotes["AAPL"]
    assert (a.kind, a.price, a.reference, a.bid, a.ask) == (STOCK, 343.39, 341.91, 343.3, 343.5)
    assert quotes["NOTRADE"].price == 10.0 and "EMPTY" not in quotes


def test_alpaca_poll_emits_only_watched(monkeypatch):
    seen, statuses = [], []
    monkeypatch.setattr(alpaca, "http_get_json", lambda url, headers, timeout=10: SNAP)

    async def go():
        p = alpaca.AlpacaProvider(seen.append, statuses.append, "k", "s")
        p.set_symbols({"AAPL"})
        await p.poll_once()
    asyncio.run(go())
    assert [q.symbol for q in seen] == ["AAPL"]


def test_alpaca_without_keys_reports_status():
    statuses = []

    async def go():
        p = alpaca.AlpacaProvider(lambda q: None, statuses.append, None, None)
        p.set_symbols({"AAPL"})
        task = asyncio.create_task(p.run())
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(go())
    assert statuses and "API keys" in statuses[0]
