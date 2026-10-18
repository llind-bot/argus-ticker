"""Entry point: python -m ticker (or ArgusTicker.exe)."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .db import Store, default_path
from .ui.main_window import MainWindow


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setOrganizationName("Argus")
    app.setApplicationName("ArgusTicker")
    store = Store(default_path())
    win = MainWindow(store)
    win.show()
    try:
        return app.exec()
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
