"""Console-less desktop entrypoint for Yggdrasil Studio v0.5.0 (PySide6)."""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from studio.app import main

if __name__ == "__main__":
    raise SystemExit(main())
