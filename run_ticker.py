"""PyInstaller entry script (keeps the package's relative imports working)."""
import sys

from ticker.app import main

sys.exit(main())
