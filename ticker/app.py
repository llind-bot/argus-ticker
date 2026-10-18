"""Entry point: python -m ticker (or ArgusTicker.exe)."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from . import selfupdate
from .db import NewerDatabase, Store, default_path
from .ui import theme
from .ui.main_window import MainWindow


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    selfupdate.cleanup_old()                          # previous version left by an update
    app = QApplication(sys.argv)
    app.setOrganizationName("Argus")
    app.setApplicationName("ArgusTicker")
    app.setApplicationDisplayName("Argus Ticker")
    app.setQuitOnLastWindowClosed(False)              # the widget/strip can run without the main window
    theme.apply_dark_palette(app)
    try:
        store = Store(default_path())
    except NewerDatabase as e:
        QMessageBox.critical(None, "Argus Ticker", str(e))
        return 1
    win = MainWindow(store)
    win.start_ui()
    try:
        return app.exec()
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
