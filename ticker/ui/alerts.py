"""Alert window: the alerts waiting for you, each with Snooze and Turn off.

An alert that fired stays here (and stays quiet, however much the price
bounces) until you act on it:

* **Snooze** — quiet for the chosen time; afterwards it fires again if the
  price is still past the level (or crosses it again).
* **Turn off alert** — clears that alert level on the asset.
* Closing the window snoozes everything left for the default time (Settings).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..format import Alert, AlertTracker

SNOOZE_CHOICES = (5, 15, 30, 60, 240, 1440)


def snooze_label(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440} day" + ("s" if minutes > 1440 else "")
    if minutes % 60 == 0:
        return f"{minutes // 60} hour" + ("s" if minutes > 60 else "")
    return f"{minutes} min"


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%I:%M %p").lstrip("0")    # %-I isn't supported on Windows


class AlertRow(QFrame):
    snooze = Signal(object, int)          # key, minutes
    turn_off = Signal(object)             # key

    def __init__(self, alert: Alert, default_min: int):
        super().__init__()
        self.key = alert.key
        self.setFrameShape(QFrame.StyledPanel)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setStyleSheet("color: gray; font-size: 11px;")
        self.minutes = QComboBox()
        choices = sorted(set(SNOOZE_CHOICES) | {default_min})
        for m in choices:
            self.minutes.addItem(snooze_label(m), m)
        self.minutes.setCurrentIndex(choices.index(default_min))
        snooze = QPushButton("Snooze")
        snooze.setDefault(True)
        snooze.clicked.connect(lambda: self.snooze.emit(self.key, self.minutes.currentData()))
        off = QPushButton("Turn off alert")
        off.setToolTip("Clear this alert level on the asset (set it again with Edit)")
        off.clicked.connect(lambda: self.turn_off.emit(self.key))
        buttons = QHBoxLayout()
        buttons.addWidget(QLabel("Quiet for"))
        buttons.addWidget(self.minutes)
        buttons.addWidget(snooze)
        buttons.addStretch(1)
        buttons.addWidget(off)
        lay = QVBoxLayout(self)
        lay.addWidget(self.text)
        lay.addWidget(self.detail)
        lay.addLayout(buttons)
        self.update_from(alert)

    def update_from(self, a: Alert) -> None:
        self.text.setText(f"<b>{a.text()}</b>")
        more = f" · crossed {a.hits}× since" if a.hits > 1 else ""
        self.detail.setText(f"First at {_when(a.first_at)}{more}")


class AlertsWindow(QDialog):
    """Non-modal, one instance; rebuilt from ``tracker.pending``."""

    def __init__(self, parent, tracker: AlertTracker, turn_off: Callable[[tuple[int, str]], None],
                 default_min: Callable[[], int]):
        super().__init__(parent)
        self.setWindowTitle("Price alerts")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumWidth(460)
        self.tracker, self._turn_off, self._default_min = tracker, turn_off, default_min
        self.rows: dict[tuple[int, str], AlertRow] = {}
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray; font-size: 11px;")
        self.box = QVBoxLayout()
        self.box.addStretch(1)
        inner = QWidget()
        inner.setLayout(self.box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QFrame.NoFrame)
        snooze_all = QPushButton("Snooze all")
        snooze_all.clicked.connect(self.snooze_all)
        bottom = QHBoxLayout()
        bottom.addWidget(self.hint, 1)
        bottom.addWidget(snooze_all)
        lay = QVBoxLayout(self)
        lay.addWidget(scroll, 1)
        lay.addLayout(bottom)
        self.timer = QTimer(self)                         # live price / hit count while open
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        pending = self.tracker.pending
        for key in [k for k in self.rows if k not in pending]:
            self.rows.pop(key).deleteLater()
        for key, a in sorted(pending.items(), key=lambda kv: kv[1].first_at):
            row = self.rows.get(key)
            if row is None:
                row = self.rows[key] = AlertRow(a, self._default_min())
                row.snooze.connect(self._snooze)
                row.turn_off.connect(self._off)
                self.box.insertWidget(self.box.count() - 1, row)
            else:
                row.update_from(a)
        self.hint.setText(f"No more pop-ups for these until you act. Closing this window snoozes them for "
                          f"{snooze_label(self._default_min())} (change it in Settings).")
        if not pending and self.isVisible():
            self.hide()

    def _snooze(self, key, minutes: int) -> None:
        self.tracker.snooze(key, minutes)
        self.refresh()

    def _off(self, key) -> None:
        self._turn_off(key)
        self.refresh()

    def snooze_all(self, minutes: int | None = None) -> None:
        for key in list(self.tracker.pending):
            self.tracker.snooze(key, minutes or self._default_min())
        self.refresh()

    def closeEvent(self, event) -> None:
        self.snooze_all()
        super().closeEvent(event)

    def reject(self) -> None:                             # Esc behaves like closing
        self.snooze_all()
        super().reject()
