"""Alert window: Snooze, Turn off, Snooze all, closing = snooze (rendered off-screen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from ticker import format as fmt
from ticker.models import CRYPTO, STOCK, Entry
from ticker.ui.alerts import AlertsWindow, snooze_label


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(app):
    now = {"t": 1_000_000.0}
    t = fmt.AlertTracker(clock=lambda: now["t"])
    btc = Entry(1, "BTC-USD", CRYPTO, alert_above=100)
    aapl = Entry(2, "AAPL", STOCK, alert_below=200)
    t.check(btc, 101)
    t.check(aapl, 199)
    turned_off = []
    w = AlertsWindow(None, t, turned_off.append, lambda: 15)
    w.show()
    return w, t, now, turned_off


def _button(row, text):
    return next(b for b in row.findChildren(QPushButton) if b.text() == text)


def test_rows_snooze_and_turn_off(setup):
    w, t, now, turned_off = setup
    assert set(w.rows) == {(1, "above"), (2, "below")}
    row = w.rows[(1, "above")]
    assert "BTC-USD is above" in row.text.text() and row.minutes.currentData() == 15
    row.minutes.setCurrentIndex(row.minutes.findData(60))
    _button(row, "Snooze").click()
    assert (1, "above") not in t.pending and t.snoozed_until((1, "above")) == now["t"] + 3600
    _button(w.rows[(2, "below")], "Turn off alert").click()
    assert turned_off == [(2, "below")]


def test_bounces_update_the_row_not_new_rows(setup):
    w, t, now, _ = setup
    btc = Entry(1, "BTC-USD", CRYPTO, alert_above=100)
    for p in (99, 103, 98, 104):
        assert t.check(btc, p) == []
    w.refresh()
    row = w.rows[(1, "above")]
    assert "crossed 3×" in row.detail.text() and "104" in row.text.text()


def test_closing_snoozes_everything_with_the_default(setup):
    w, t, now, _ = setup
    w.close()
    assert t.pending == {} and t.snoozed_until((2, "below")) == now["t"] + 900


def test_snooze_labels():
    assert [snooze_label(m) for m in (5, 60, 240, 1440)] == ["5 min", "1 hour", "4 hours", "1 day"]
