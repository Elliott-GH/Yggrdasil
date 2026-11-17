"""Console-less Windows desktop launcher (.pyw) for Yggdrasil Sovereign Studio v0.3.0."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from native_gui import main

if __name__ == "__main__":
    raise SystemExit(main())
