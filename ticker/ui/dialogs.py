"""Add/edit entry and settings dialogs."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QVBoxLayout)

from .. import settings
from ..models import CRYPTO, STOCK, Entry, normalize, valid_format
from ..providers import alpaca, coinbase


def _opt_float(text: str) -> Optional[float]:
    text = text.strip().replace(",", "").lstrip("$")
    return float(text) if text else None


class EntryDialog(QDialog):
    """Add or edit a watchlist entry; checks the symbol with its provider before saving."""

    def __init__(self, parent=None, entry: Optional[Entry] = None,
                 keys: Callable[[], tuple] = lambda: (None, None), feed: str = "iex"):
        super().__init__(parent)
        self.setWindowTitle("Edit entry" if entry else "Add entry")
        self._entry, self._keys, self._feed = entry, keys, feed
        self.kind = QComboBox()
        self.kind.addItem("Stock (Alpaca)", STOCK)
        self.kind.addItem("Crypto (Coinbase)", CRYPTO)
        self.symbol = QLineEdit()
        self.name = QLineEdit()
        self.above = QLineEdit()
        self.below = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(70)
        for w, hint in ((self.above, "optional, e.g. 250"), (self.below, "optional")):
            w.setPlaceholderText(hint)
        self.kind.currentIndexChanged.connect(self._hint)
        if entry:
            self.kind.setCurrentIndex(self.kind.findData(entry.kind))
            self.symbol.setText(entry.symbol)
            self.name.setText(entry.name)
            self.above.setText("" if entry.alert_above is None else f"{entry.alert_above:g}")
            self.below.setText("" if entry.alert_below is None else f"{entry.alert_below:g}")
            self.notes.setPlainText(entry.notes)
        self._hint()

        form = QFormLayout()
        form.addRow("Type", self.kind)
        form.addRow("Symbol", self.symbol)
        form.addRow("Name", self.name)
        form.addRow("Alert above", self.above)
        form.addRow("Alert below", self.below)
        form.addRow("Notes", self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)
        self.result_entry: Optional[Entry] = None

    def _hint(self) -> None:
        self.symbol.setPlaceholderText("e.g. AAPL" if self.kind.currentData() == STOCK else "e.g. BTC or ETH-USD")

    def _save(self) -> None:
        kind = self.kind.currentData()
        sym = normalize(self.symbol.text(), kind)
        if not valid_format(sym, kind):
            QMessageBox.warning(self, "Symbol", f"“{self.symbol.text().strip()}” doesn't look like a "
                                f"{'stock symbol' if kind == STOCK else 'crypto pair (e.g. BTC-USD)'}.")
            return
        try:
            above, below = _opt_float(self.above.text()), _opt_float(self.below.text())
        except ValueError:
            QMessageBox.warning(self, "Alert", "Alert levels must be numbers.")
            return
        changed = not self._entry or (sym, kind) != (self._entry.symbol, self._entry.kind)
        if changed and not self._check(sym, kind):
            return
        e = self._entry or Entry(None, sym, kind)
        self.result_entry = Entry(e.id, sym, kind, self.name.text().strip(), self.notes.toPlainText().strip(),
                                  above, below, e.sort)
        self.accept()

    def _check(self, sym: str, kind: str) -> bool:
        """True to save. Unknown symbol → stop; can't reach the provider → ask."""
        key, secret = self._keys()
        if kind == STOCK and not (key and secret):
            return True                                   # can't check without keys
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = coinbase.validate(sym) if kind == CRYPTO else alpaca.validate(sym, key, secret, self._feed)
            err = None
        except Exception as e:                           # noqa: BLE001 — offline, auth, …
            ok, err = None, e
        finally:
            QGuiApplication.restoreOverrideCursor()
        if ok:
            return True
        if ok is False:
            QMessageBox.warning(self, "Symbol", f"{'Coinbase' if kind == CRYPTO else 'Alpaca'} doesn't know {sym}.")
            return False
        return QMessageBox.question(self, "Couldn't check symbol",
                                    f"Couldn't check {sym} ({err}). Save it anyway?") == QMessageBox.Yes


class SettingsDialog(QDialog):
    def __init__(self, parent, prefs: settings.Prefs, has_keys: bool):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.key, self.secret = QLineEdit(), QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        self.key.setEchoMode(QLineEdit.Password)
        self.clear = QCheckBox("Remove saved keys")
        self.feed = QComboBox()
        self.feed.addItem("IEX (free plan)", "iex")
        self.feed.addItem("SIP — all exchanges (paid plan)", "sip")
        self.feed.setCurrentIndex(max(0, self.feed.findData(prefs.feed)))
        self.interval = QDoubleSpinBox()
        self.interval.setRange(2, 300)
        self.interval.setSuffix(" s")
        self.interval.setValue(prefs.interval)
        self.on_top = QCheckBox("Keep window on top")
        self.on_top.setChecked(prefs.always_on_top)

        if settings.keys_from_env():
            note = "Using ALPACA_API_KEY / ALPACA_SECRET_KEY from the environment."
            for w in (self.key, self.secret, self.clear):
                w.setEnabled(False)
        else:
            note = ("Keys are saved in Windows Credential Manager. " +
                    ("Leave blank to keep the saved keys." if has_keys else "No keys saved yet."))
        form = QFormLayout()
        form.addRow("Alpaca API key", self.key)
        form.addRow("Alpaca secret", self.secret)
        form.addRow("", self.clear)
        form.addRow("", QLabel(note))
        form.addRow("Stock data feed", self.feed)
        form.addRow("Stock refresh", self.interval)
        form.addRow("", self.on_top)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)
        self.prefs = prefs
        self.keys_changed = False

    def _save(self) -> None:
        key, secret = self.key.text().strip(), self.secret.text().strip()
        if bool(key) != bool(secret):
            QMessageBox.warning(self, "Alpaca keys", "Enter both the API key and the secret.")
            return
        try:
            if self.clear.isChecked():
                settings.save_keys("", "")
                self.keys_changed = True
            elif key:
                settings.save_keys(key, secret)
                self.keys_changed = True
        except Exception as e:                           # noqa: BLE001
            QMessageBox.critical(self, "Alpaca keys", f"Couldn't save the keys: {e}")
            return
        self.prefs = settings.Prefs(self.feed.currentData(), self.interval.value(), self.on_top.isChecked())
        settings.save_prefs(self.prefs)
        self.accept()
