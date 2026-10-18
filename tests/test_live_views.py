"""Live state rows and painted views (rendered off-screen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ticker import market
from ticker.models import CRYPTO, STOCK, Entry, Quote
from ticker.ui.live_views import CardsView, ListView
from ticker.ui.overlays import FloatingWidget, TickerStrip
from ticker.ui.state import LiveState


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setOrganizationName("ArgusTest")
    a.setApplicationName("ArgusTickerTest")
    return a


@pytest.fixture
def state(app):
    s = LiveState()
    s.set_entries([Entry(1, "BTC-USD", CRYPTO, "Bitcoin"), Entry(2, "AAPL", STOCK, "Apple")])
    s.set_market(market.Market(False))
    s.update_quotes([Quote("BTC-USD", CRYPTO, 110.0, 100.0), Quote("AAPL", STOCK, 95.0, 100.0)])
    s.set_history({("BTC-USD", CRYPTO): [100.0, 105.0], ("AAPL", STOCK): [100.0, 97.0]})
    return s


def test_rows(state):
    btc, aapl = state.rows()
    assert (btc.short, btc.price, btc.pct, btc.up, btc.live) == ("BTC", "110.00", "+10.00%", True, True)
    assert btc.points == [100.0, 105.0, 110.0]                  # ends at the live price
    assert (aapl.up, aapl.live, aapl.color) == (False, False, state.down_color)   # market closed
    state.update_quotes([Quote("BTC-USD", CRYPTO, 111.0, 100.0)])
    assert state.rows(CRYPTO)[0].flash == 1
    state.set_scheme("blue-orange")
    assert state.rows(CRYPTO)[0].color.name() == "#4c9aff"


@pytest.mark.parametrize("cls", [CardsView, ListView, FloatingWidget, TickerStrip])
def test_views_paint(state, cls):
    v = cls(state)
    if cls in (CardsView, ListView):
        v.resize(800, 400)
    img = v.grab()
    assert not img.isNull() and img.width() > 0
    v.close()


def test_cards_columns_and_height(state):
    v = CardsView(state)
    assert v._cols(900) == 3 and v._cols(300) == 1
    assert v.content_height(300) > v.content_height(900)
