"""Yggdrasil Sovereign Studio v0.5.0 — Standalone Gemini Interactive Workspace Entrypoint."""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "app-0.5.0"
AGENTS_DIR = BASE_DIR / "agents_and_lms"
LOG_DIR = BASE_DIR / "logs"
VENV_CANDIDATES = (
    BASE_DIR / ".venv" / "Scripts" / "pythonw.exe",
    Path(r"C:\AntiGravityFiles\MasterAgent\.venv\Scripts\pythonw.exe"),
)


def _report_fatal(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "launch_error.log").write_text(message, encoding="utf-8")
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Yggdrasil Studio v0.5.0 failed to start", message[-1800:])
        root.destroy()
    except Exception:
        pass


def _relaunch_with_venv() -> bool:
    if os.environ.get("YGG_RELAUNCHED") == "1":
        return False
    current = Path(sys.executable).resolve()
    for cand in VENV_CANDIDATES:
        if cand.exists() and cand.resolve() != current:
            env = dict(os.environ, YGG_RELAUNCHED="1")
            env.pop("PYTHONPATH", None)
            cmd = [str(cand), str(Path(__file__).resolve()), *sys.argv[1:]]
            subprocess.Popen(cmd, env=env)
            return True
    return False


for cand_dir in (str(APP_DIR), str(AGENTS_DIR)):
    if cand_dir not in sys.path:
        sys.path.insert(0, cand_dir)

try:
    import PySide6  # noqa: F401
    from studio.app import main
except ImportError:
    if not _relaunch_with_venv():
        _report_fatal(
            "Missing Python/PySide6 dependencies for interpreter:\n"
            + sys.executable
            + "\n\n"
            + traceback.format_exc()
        )
    raise SystemExit(0) from None

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        _report_fatal(traceback.format_exc())
        raise SystemExit(1) from None
