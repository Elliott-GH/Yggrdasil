"""Automated packager & backup sync from MasterAgent into C:\\AntiGravityFiles\\output\\."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
FOUNDRY_DIR = REPO_ROOT / "03-agent-foundry"
DEFAULT_OUTPUT_ROOT = Path(os.getenv("YGGDRASIL_OUTPUT_ROOT", r"C:\AntiGravityFiles\output"))

for _cand in (str(APP_DIR), str(FOUNDRY_DIR)):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)

from exported_nano_agents import get_exported_nano_manifest

from yggdrasil_agents.nano_models import (
    DEFAULT_MICRO_WEIGHTS_1024,
    UiThemeSpec,
    build_native_tk_style_tokens,
)


def _copy_tree_clean(src: Path, dst: Path, exclude_names: set[str] | None = None) -> None:
    """Recursively copy a directory excluding bytecode caches and transient artifacts."""
    if dst.exists():
        shutil.rmtree(dst)
    skip = (exclude_names or set()) | {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}

    def _ignore(_dir: str, entries: list[str]) -> set[str]:
        return {name for name in entries if name in skip or name.endswith((".pyc", ".pyo"))}

    shutil.copytree(src, dst, ignore=_ignore)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def _init_vault_dbs(vaults_dir: Path) -> None:
    """Create clean empty schema SQLite vaults if not already present in destination."""
    vaults_dir.mkdir(parents=True, exist_ok=True)
    pv = vaults_dir / "personal_vault.db"
    if not pv.exists():
        with sqlite3.connect(pv) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    privacy_tier TEXT NOT NULL DEFAULT 'air_gapped'
                        CHECK (privacy_tier = 'air_gapped'),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
    st = vaults_dir / "state_tree.db"
    if not st.exists():
        with sqlite3.connect(st) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tree_nodes (
                    node_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    label TEXT NOT NULL,
                    tier TEXT NOT NULL CHECK (tier IN ('roots', 'trunk', 'twigs', 'leaves')),
                    initial_weight REAL NOT NULL DEFAULT 1.0,
                    decay_rate REAL NOT NULL DEFAULT 0.05,
                    resonance_count INTEGER NOT NULL DEFAULT 0,
                    current_weight REAL NOT NULL DEFAULT 1.0,
                    contains_personal_vault_data INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()


def _populate_user_content(uc_root: Path, manifest_json: str, weights_json: str) -> None:
    """Populate Antigravity/Gemini-style user_content directories cleanly."""
    for sub in ("brain", "instructions", "exports", "workspaces"):
        (uc_root / sub).mkdir(parents=True, exist_ok=True)
    _copy_tree_clean(REPO_ROOT / ".agents" / "skills", uc_root / "instructions" / "skills")
    _copy_tree_clean(REPO_ROOT / ".agents" / "agents", uc_root / "instructions" / "agents")
    (uc_root / "instructions" / "sample_prompts.md").write_text(
        "# Yggdrasil Studio Sample Prompts\n\n"
        "- `#CALC_SOLVE`: `1e8 * exp(-50000 / (8.31446261815324 * 350))`\n"
        "- `#CONTROL_SYSTEM`: `kp=2.0 tau=10.0 theta=2.0 controller_type=PID tuning_method=imc`\n"
        "- `[/userinterface] Apply compact dark mode with fast animation`\n",
        encoding="utf-8",
    )
    (uc_root / "exports" / "nano_agents_manifest.json").write_text(manifest_json, encoding="utf-8")
    (uc_root / "exports" / "micro_model_1024_weights.json").write_text(weights_json, encoding="utf-8")
    (uc_root / "workspaces" / "README.md").write_text(
        "# User Workspaces\n\nPlace local CSV, Office, PDF, or Python files here for offline analysis.\n",
        encoding="utf-8",
    )


def _write_v2_launchers(v2_dir: Path) -> None:
    bat_v2 = """@echo off
setlocal
set "VDIR=%~dp0"
if exist "%VDIR%.venv\\Scripts\\python.exe" (
  set "PY=%VDIR%.venv\\Scripts\\python.exe"
) else if exist "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe" (
  set "PY=C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe"
) else (
  set "PY=python"
)
set "PYTHONPATH="
"%PY%" "%VDIR%executables\\yggdrasil_studio.py" %*
"""
    ps1_v2 = """param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)
$vdir = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(
    (Join-Path $vdir ".venv\\Scripts\\python.exe"),
    "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe",
    "python"
)
$py = $candidates | Where-Object { $_ -eq "python" -or (Test-Path $_) } | Select-Object -First 1
$env:PYTHONPATH = ""
& $py (Join-Path $vdir "executables\\yggdrasil_studio.py") @ExtraArgs
"""
    (v2_dir / "Launch-Yggdrasil-Studio.bat").write_text(bat_v2, encoding="utf-8")
    (v2_dir / "Launch-Yggdrasil-Studio.ps1").write_text(ps1_v2, encoding="utf-8")


def _write_v3_and_root_launchers(v3_dir: Path, output_root: Path) -> None:
    """Write console-less .pyw desktop launcher + Gemini-style AppLauncher scripts."""
    v3_pyw = """\"\"\"Yggdrasil Sovereign Studio v0.3.0 — Standalone Native Desktop Entrypoint.\"\"\"

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "app-0.3.0"
AGENTS_DIR = BASE_DIR / "agents_and_lms"
LOG_DIR = BASE_DIR / "logs"
VENV_CANDIDATES = (
    BASE_DIR / ".venv" / "Scripts" / "pythonw.exe",
    Path(r"C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\pythonw.exe"),
)


def _report_fatal(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "launch_error.log").write_text(message, encoding="utf-8")
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Yggdrasil failed to start", message[-1800:])
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
            subprocess.Popen([str(cand), str(Path(__file__).resolve()), *sys.argv[1:]], env=env)
            return True
    return False


for cand_dir in (str(APP_DIR), str(AGENTS_DIR)):
    if cand_dir not in sys.path:
        sys.path.insert(0, cand_dir)

try:
    from native_gui import main
except ImportError:
    if not _relaunch_with_venv():
        _report_fatal(
            "Missing Python dependencies for interpreter:\\n" + sys.executable + "\\n\\n"
            + traceback.format_exc()
            + "\\nFix: install requirements (pydantic, pydantic-ai, pypdf, httpx) into this Python."
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
"""
    (v3_dir / "Yggdrasil.pyw").write_text(v3_pyw, encoding="utf-8")

    bat_v3 = """@echo off
setlocal
set "VDIR=%~dp0"
set "PYTHONPATH="
set "PYDIR=C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts"
if exist "%VDIR%.venv\\Scripts\\python.exe" set "PYDIR=%VDIR%.venv\\Scripts"
if not exist "%PYDIR%\\python.exe" goto :no_python
if not "%~1"=="" goto :cli
start "Yggdrasil" "%PYDIR%\\pythonw.exe" "%VDIR%Yggdrasil.pyw"
exit /b 0
:cli
"%PYDIR%\\python.exe" "%VDIR%app-0.3.0\\native_gui.py" %*
exit /b %ERRORLEVEL%
:no_python
echo [Yggdrasil] No Python environment found.
echo Expected: %VDIR%.venv\\Scripts\\python.exe
echo       or: C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe
pause
exit /b 1
"""
    ps1_v3 = """param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)
$vdir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = ""
if ($ExtraArgs.Count -eq 0) {
    $candidates = @(
        (Join-Path $vdir ".venv\\Scripts\\pythonw.exe"),
        "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\pythonw.exe",
        "pythonw"
    )
    $pyw = $candidates | Where-Object { $_ -eq "pythonw" -or (Test-Path $_) } | Select-Object -First 1
    Start-Process -FilePath $pyw -ArgumentList "`"$(Join-Path $vdir 'Yggdrasil.pyw')`""
} else {
    $candidates = @(
        (Join-Path $vdir ".venv\\Scripts\\python.exe"),
        "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe",
        "python"
    )
    $py = $candidates | Where-Object { $_ -eq "python" -or (Test-Path $_) } | Select-Object -First 1
    & $py (Join-Path $vdir "app-0.3.0\\native_gui.py") @ExtraArgs
}
"""
    (v3_dir / "YggdrasilAppLauncher.bat").write_text(bat_v3, encoding="utf-8")
    (v3_dir / "YggdrasilAppLauncher.ps1").write_text(ps1_v3, encoding="utf-8")


def _write_v4_and_root_launchers(v4_dir: Path, output_root: Path) -> None:
    """Write Version 4 PySide6 Gemini Studio .pyw launcher + root launchers."""
    v4_pyw = """\"\"\"Yggdrasil Sovereign Studio v0.4.0 — Standalone Gemini-Clone PySide6 Entrypoint.\"\"\"

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "app-0.4.0"
AGENTS_DIR = BASE_DIR / "agents_and_lms"
LOG_DIR = BASE_DIR / "logs"
VENV_CANDIDATES = (
    BASE_DIR / ".venv" / "Scripts" / "pythonw.exe",
    Path(r"C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\pythonw.exe"),
)


def _report_fatal(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "launch_error.log").write_text(message, encoding="utf-8")
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Yggdrasil Studio v0.4.0 failed to start", message[-1800:])
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
            "Missing Python/PySide6 dependencies for interpreter:\\n"
            + sys.executable
            + "\\n\\n"
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
"""
    (v4_dir / "Yggdrasil.pyw").write_text(v4_pyw, encoding="utf-8")

    bat_v4 = """@echo off
setlocal
set "VDIR=%~dp0"
set "PYTHONPATH="
set "PYDIR=C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts"
if exist "%VDIR%.venv\\Scripts\\python.exe" set "PYDIR=%VDIR%.venv\\Scripts"
if not exist "%PYDIR%\\python.exe" goto :no_python
if not "%~1"=="" goto :cli
start "YggdrasilStudio" "%PYDIR%\\pythonw.exe" "%VDIR%Yggdrasil.pyw"
exit /b 0
:cli
"%PYDIR%\\python.exe" "%VDIR%app-0.4.0\\YggdrasilStudio.pyw" %*
exit /b %ERRORLEVEL%
:no_python
echo [Yggdrasil] No Python environment found.
echo Expected: %VDIR%.venv\\Scripts\\python.exe
echo       or: C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe
pause
exit /b 1
"""
    ps1_v4 = """param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)
$vdir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = ""
if ($ExtraArgs.Count -eq 0) {
    $candidates = @(
        (Join-Path $vdir ".venv\\Scripts\\pythonw.exe"),
        "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\pythonw.exe",
        "pythonw"
    )
    $pyw = $candidates | Where-Object { $_ -eq "pythonw" -or (Test-Path $_) } | Select-Object -First 1
    Start-Process -FilePath $pyw -ArgumentList "`"$(Join-Path $vdir 'Yggdrasil.pyw')`""
} else {
    $candidates = @(
        (Join-Path $vdir ".venv\\Scripts\\python.exe"),
        "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe",
        "python"
    )
    $py = $candidates | Where-Object { $_ -eq "python" -or (Test-Path $_) } | Select-Object -First 1
    & $py (Join-Path $vdir "app-0.4.0\\YggdrasilStudio.pyw") @ExtraArgs
}
"""
    (v4_dir / "YggdrasilAppLauncher.bat").write_text(bat_v4, encoding="utf-8")
    (v4_dir / "YggdrasilAppLauncher.ps1").write_text(ps1_v4, encoding="utf-8")


def _write_v5_and_root_launchers(v5_dir: Path, output_root: Path) -> None:
    """Write Version 5 PySide6 Gemini Interactive Workspace .pyw launcher + root launchers."""
    v5_pyw = """\"\"\"Yggdrasil Sovereign Studio v0.5.0 — Standalone Gemini Interactive Workspace Entrypoint.\"\"\"

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
    Path(r"C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\pythonw.exe"),
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
            "Missing Python/PySide6 dependencies for interpreter:\\n"
            + sys.executable
            + "\\n\\n"
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
"""
    (v5_dir / "Yggdrasil.pyw").write_text(v5_pyw, encoding="utf-8")

    bat_v5 = """@echo off
setlocal
set "VDIR=%~dp0"
set "PYTHONPATH="
set "PYDIR=C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts"
if exist "%VDIR%.venv\\Scripts\\python.exe" set "PYDIR=%VDIR%.venv\\Scripts"
if not exist "%PYDIR%\\python.exe" goto :no_python
if not "%~1"=="" goto :cli
start "YggdrasilStudioV5" "%PYDIR%\\pythonw.exe" "%VDIR%Yggdrasil.pyw"
exit /b 0
:cli
"%PYDIR%\\python.exe" "%VDIR%app-0.5.0\\YggdrasilStudio.pyw" %*
exit /b %ERRORLEVEL%
:no_python
echo [Yggdrasil] No Python environment found.
echo Expected: %VDIR%.venv\\Scripts\\python.exe
echo       or: C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe
pause
exit /b 1
"""
    ps1_v5 = """param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)
$vdir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = ""
if ($ExtraArgs.Count -eq 0) {
    $candidates = @(
        (Join-Path $vdir ".venv\\Scripts\\pythonw.exe"),
        "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\pythonw.exe",
        "pythonw"
    )
    $pyw = $candidates | Where-Object { $_ -eq "pythonw" -or (Test-Path $_) } | Select-Object -First 1
    Start-Process -FilePath $pyw -ArgumentList "`"$(Join-Path $vdir 'Yggdrasil.pyw')`""
} else {
    $candidates = @(
        (Join-Path $vdir ".venv\\Scripts\\python.exe"),
        "C:\\AntiGravityFiles\\MasterAgent\\.venv\\Scripts\\python.exe",
        "python"
    )
    $py = $candidates | Where-Object { $_ -eq "python" -or (Test-Path $_) } | Select-Object -First 1
    & $py (Join-Path $vdir "app-0.5.0\\YggdrasilStudio.pyw") @ExtraArgs
}
"""
    (v5_dir / "YggdrasilAppLauncher.bat").write_text(bat_v5, encoding="utf-8")
    (v5_dir / "YggdrasilAppLauncher.ps1").write_text(ps1_v5, encoding="utf-8")

    root_pyw = """\"\"\"Root launcher forwarding directly to Version 5\\Yggdrasil.pyw.\"\"\"

from __future__ import annotations

import runpy
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "Version 5" / "Yggdrasil.pyw"
runpy.run_path(str(TARGET), run_name="__main__")
"""
    (output_root / "Yggdrasil.pyw").write_text(root_pyw, encoding="utf-8")

    root_bat = """@echo off
call "%~dp0Version 5\\YggdrasilAppLauncher.bat" %*
"""
    root_ps1 = """param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)
& (Join-Path $PSScriptRoot "Version 5\\YggdrasilAppLauncher.ps1") @ExtraArgs
"""
    (output_root / "Launch-Yggdrasil.bat").write_text(root_bat, encoding="utf-8")
    (output_root / "Launch-Yggdrasil.ps1").write_text(root_ps1, encoding="utf-8")


def sync_output_distributions(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    """Build and synchronize self-sufficient Version 1, Version 2, and Version 3 bundles."""
    output_root.mkdir(parents=True, exist_ok=True)
    changelog_src = REPO_ROOT / "Changelog"

    manifest_json = json.dumps(
        [item.model_dump(mode="json") for item in get_exported_nano_manifest()],
        indent=2,
    )
    weights_json = json.dumps(DEFAULT_MICRO_WEIGHTS_1024, indent=2)
    tk_tokens_json = json.dumps(
        build_native_tk_style_tokens(UiThemeSpec(ui_mode="native_desktop")),
        indent=2,
    )

    from studio.store import StudioStore

    # --- Version 1 (v0.1.0 Baseline Prototype Backup) ---
    v1 = output_root / "Version 1"
    if not v1.exists():
        for name in ("MasterChangelog0.1.md", "YggrdasilChangelog0.1.md", "EmbedAgentChangelog0.1.md"):
            _copy_file(changelog_src / name, v1 / "Changelog" / name)
        _copy_tree_clean(
            FOUNDRY_DIR / "yggdrasil_agents",
            v1 / "agents_and_lms" / "yggdrasil_agents",
            exclude_names={"ui_agent.py"},
        )
        _copy_file(
            FOUNDRY_DIR / "modelfiles" / "Modelfile.yggdrasil-nano",
            v1 / "agents_and_lms" / "Modelfile.yggdrasil-nano",
        )
        _copy_file(FOUNDRY_DIR / "pyproject.toml", v1 / "agents_and_lms" / "pyproject.toml")
        _copy_file(APP_DIR / "app.py", v1 / "executables" / "app.py")
        _copy_file(APP_DIR / "exported_nano_agents.py", v1 / "executables" / "exported_nano_agents.py")
        _copy_file(APP_DIR / "vaults" / "references.json", v1 / "data_and_vaults" / "references.json")
        _copy_file(APP_DIR / ".env.example", v1 / "data_and_vaults" / ".env.example")
        _init_vault_dbs(v1 / "data_and_vaults")
        _copy_file(REPO_ROOT / "AGENTS.md", v1 / "markdowns_and_specs" / "AGENTS.md")
        _copy_file(REPO_ROOT / "PROJECT_STATE.md", v1 / "markdowns_and_specs" / "PROJECT_STATE.md")
        _copy_file(
            REPO_ROOT / "02-yggdrasil-lab" / "specs" / "000-foundational-architecture-spec.md",
            v1 / "markdowns_and_specs" / "000-foundational-architecture-spec.md",
        )
        _copy_file(
            REPO_ROOT / "02-yggdrasil-lab" / "specs" / "001-nested-nano-models-and-deterministic-tools-spec.md",
            v1 / "markdowns_and_specs" / "001-nested-nano-models-and-deterministic-tools-spec.md",
        )

    # --- Version 2 (v0.2.0 Web Studio Prototype Backup) ---
    v2 = output_root / "Version 2"
    if not v2.exists():
        v2.mkdir(parents=True, exist_ok=True)
        for name in (
            "CHANGELOG_INDEX.md",
            "MasterChangelog0.1.md",
            "MasterChangelog0.2.md",
            "YggrdasilChangelog0.1.md",
            "YggrdasilChangelog0.2.md",
            "EmbedAgentChangelog0.1.md",
            "EmbedAgentChangelog0.2.md",
        ):
            _copy_file(changelog_src / name, v2 / "Changelog" / name)
        _copy_tree_clean(FOUNDRY_DIR / "yggdrasil_agents", v2 / "agents_and_lms" / "yggdrasil_agents")
        _copy_file(
            FOUNDRY_DIR / "modelfiles" / "Modelfile.yggdrasil-nano",
            v2 / "agents_and_lms" / "Modelfile.yggdrasil-nano",
        )
        _copy_file(FOUNDRY_DIR / "pyproject.toml", v2 / "agents_and_lms" / "pyproject.toml")
        (v2 / "agents_and_lms" / "nano_agents_manifest.json").write_text(manifest_json, encoding="utf-8")
        (v2 / "agents_and_lms" / "micro_model_1024_weights.json").write_text(weights_json, encoding="utf-8")
        _copy_file(APP_DIR / "gui_app.py", v2 / "executables" / "yggdrasil_studio.py")
        _copy_file(APP_DIR / "app.py", v2 / "executables" / "app.py")
        _copy_file(APP_DIR / "exported_nano_agents.py", v2 / "executables" / "exported_nano_agents.py")
        _copy_file(APP_DIR / "dist_sync.py", v2 / "executables" / "dist_sync.py")
        _copy_file(APP_DIR / "vaults" / "references.json", v2 / "data_and_vaults" / "references.json")
        _copy_file(APP_DIR / ".env.example", v2 / "data_and_vaults" / ".env.example")
        _init_vault_dbs(v2 / "data_and_vaults")
        _copy_file(REPO_ROOT / "AGENTS.md", v2 / "markdowns_and_specs" / "AGENTS.md")
        _copy_file(REPO_ROOT / "PROJECT_STATE.md", v2 / "markdowns_and_specs" / "PROJECT_STATE.md")
        _copy_tree_clean(REPO_ROOT / "02-yggdrasil-lab" / "specs", v2 / "markdowns_and_specs" / "specs")
        _copy_file(
            REPO_ROOT / "01-code-oracle" / "001-nano-routing-and-deterministic-tools-grounding.md",
            v2 / "markdowns_and_specs" / "001-nano-routing-and-deterministic-tools-grounding.md",
        )
        _populate_user_content(v2 / "user_content", manifest_json, weights_json)
        _write_v2_launchers(v2)

    # --- Version 3 (v0.3.0 Non-Web Native Desktop Software Release — Gemini Layout) ---
    v3 = output_root / "Version 3"
    if not v3.exists():
        v3.mkdir(parents=True, exist_ok=True)
        if changelog_src.exists():
            for ch_file in changelog_src.glob("*.md"):
                _copy_file(ch_file, v3 / "Changelog" / ch_file.name)

        _copy_tree_clean(FOUNDRY_DIR / "yggdrasil_agents", v3 / "agents_and_lms" / "yggdrasil_agents")
        _copy_file(
            FOUNDRY_DIR / "modelfiles" / "Modelfile.yggdrasil-nano",
            v3 / "agents_and_lms" / "Modelfile.yggdrasil-nano",
        )
        _copy_file(FOUNDRY_DIR / "pyproject.toml", v3 / "agents_and_lms" / "pyproject.toml")

        app_v3 = v3 / "app-0.3.0"
        _copy_file(APP_DIR / "native_gui.py", app_v3 / "native_gui.py")
        _copy_file(APP_DIR / "YggdrasilDesktop.pyw", app_v3 / "YggdrasilDesktop.pyw")
        _copy_file(APP_DIR / "gui_app.py", app_v3 / "gui_app.py")
        _copy_file(APP_DIR / "app.py", app_v3 / "app.py")
        _copy_file(APP_DIR / "exported_nano_agents.py", app_v3 / "exported_nano_agents.py")
        _copy_file(APP_DIR / "dist_sync.py", app_v3 / "dist_sync.py")

        res_v3 = v3 / "resources"
        res_v3.mkdir(parents=True, exist_ok=True)
        (res_v3 / "tk_theme_tokens.json").write_text(tk_tokens_json, encoding="utf-8")
        (res_v3 / "nano_agents_manifest.json").write_text(manifest_json, encoding="utf-8")
        (res_v3 / "micro_model_1024_weights.json").write_text(weights_json, encoding="utf-8")
        (v3 / "logs").mkdir(parents=True, exist_ok=True)
        (v3 / "version").write_text("0.3.0\n", encoding="utf-8")
        (v3 / "YGGDRASIL_BUILD_INFO.txt").write_text(
            "Product: Yggdrasil Sovereign Studio\n"
            "Version: 0.3.0\n"
            "UI Runtime: Native Tkinter/TTK Desktop (.pyw, zero browser)\n"
            "Spec: SPEC-003\n",
            encoding="utf-8",
        )

        _copy_file(APP_DIR / "vaults" / "references.json", v3 / "data_and_vaults" / "references.json")
        _copy_file(APP_DIR / ".env.example", v3 / "data_and_vaults" / ".env.example")
        _init_vault_dbs(v3 / "data_and_vaults")

        _copy_file(REPO_ROOT / "AGENTS.md", v3 / "markdowns_and_specs" / "AGENTS.md")
        _copy_file(REPO_ROOT / "PROJECT_STATE.md", v3 / "markdowns_and_specs" / "PROJECT_STATE.md")
        _copy_tree_clean(REPO_ROOT / "02-yggdrasil-lab" / "specs", v3 / "markdowns_and_specs" / "specs")
        _copy_file(
            REPO_ROOT / "01-code-oracle" / "001-nano-routing-and-deterministic-tools-grounding.md",
            v3 / "markdowns_and_specs" / "001-nano-routing-and-deterministic-tools-grounding.md",
        )
        _populate_user_content(v3 / "user_content", manifest_json, weights_json)
        _write_v3_and_root_launchers(v3, output_root)

    # --- Version 4 (v0.4.0 Gemini-Clone PySide6 Desktop Studio — SPEC-004) ---
    v4 = output_root / "Version 4"
    if not v4.exists():
        v4.mkdir(parents=True, exist_ok=True)
        if changelog_src.exists():
            for ch_file in changelog_src.glob("*.md"):
                _copy_file(ch_file, v4 / "Changelog" / ch_file.name)

        _copy_tree_clean(FOUNDRY_DIR / "yggdrasil_agents", v4 / "agents_and_lms" / "yggdrasil_agents")
        _copy_file(
            FOUNDRY_DIR / "modelfiles" / "Modelfile.yggdrasil-nano",
            v4 / "agents_and_lms" / "Modelfile.yggdrasil-nano",
        )
        _copy_file(FOUNDRY_DIR / "pyproject.toml", v4 / "agents_and_lms" / "pyproject.toml")

        app_v4 = v4 / "app-0.4.0"
        _copy_tree_clean(APP_DIR / "studio", app_v4 / "studio")
        _copy_file(APP_DIR / "YggdrasilStudio.pyw", app_v4 / "YggdrasilStudio.pyw")
        _copy_file(APP_DIR / "native_gui.py", app_v4 / "native_gui.py")
        _copy_file(APP_DIR / "YggdrasilDesktop.pyw", app_v4 / "YggdrasilDesktop.pyw")
        _copy_file(APP_DIR / "gui_app.py", app_v4 / "gui_app.py")
        _copy_file(APP_DIR / "app.py", app_v4 / "app.py")
        _copy_file(APP_DIR / "exported_nano_agents.py", app_v4 / "exported_nano_agents.py")
        _copy_file(APP_DIR / "dist_sync.py", app_v4 / "dist_sync.py")

        res_v4 = v4 / "resources"
        res_v4.mkdir(parents=True, exist_ok=True)
        (res_v4 / "tk_theme_tokens.json").write_text(tk_tokens_json, encoding="utf-8")
        (res_v4 / "nano_agents_manifest.json").write_text(manifest_json, encoding="utf-8")
        (res_v4 / "micro_model_1024_weights.json").write_text(weights_json, encoding="utf-8")
        (v4 / "logs").mkdir(parents=True, exist_ok=True)
        (v4 / "version").write_text("0.4.0\n", encoding="utf-8")
        (v4 / "YGGDRASIL_BUILD_INFO.txt").write_text(
            "Product: Yggdrasil Sovereign Studio\n"
            "Version: 0.4.0\n"
            "UI Runtime: Native PySide6 / Qt6 Gemini-Clone Desktop Studio (.pyw, zero browser)\n"
            "Spec: SPEC-004\n",
            encoding="utf-8",
        )

        _copy_file(APP_DIR / "vaults" / "references.json", v4 / "data_and_vaults" / "references.json")
        _copy_file(APP_DIR / ".env.example", v4 / "data_and_vaults" / ".env.example")
        _init_vault_dbs(v4 / "data_and_vaults")

        v4_store = StudioStore(v4 / "data_and_vaults" / "studio.db")
        v4_store.seed_defaults_if_empty()
        v4_store.close()

        _copy_file(REPO_ROOT / "AGENTS.md", v4 / "markdowns_and_specs" / "AGENTS.md")
        _copy_file(REPO_ROOT / "PROJECT_STATE.md", v4 / "markdowns_and_specs" / "PROJECT_STATE.md")
        _copy_tree_clean(REPO_ROOT / "02-yggdrasil-lab" / "specs", v4 / "markdowns_and_specs" / "specs")
        _copy_file(
            REPO_ROOT / "01-code-oracle" / "001-nano-routing-and-deterministic-tools-grounding.md",
            v4 / "markdowns_and_specs" / "001-nano-routing-and-deterministic-tools-grounding.md",
        )
        _populate_user_content(v4 / "user_content", manifest_json, weights_json)
        _write_v4_and_root_launchers(v4, output_root)

    # --- Version 5 (v0.5.0 Gemini Interactive Workspace + Antigravity SDK — SPEC-005) ---
    v5 = output_root / "Version 5"
    v5.mkdir(parents=True, exist_ok=True)
    if changelog_src.exists():
        for ch_file in changelog_src.glob("*.md"):
            _copy_file(ch_file, v5 / "Changelog" / ch_file.name)

    _copy_tree_clean(FOUNDRY_DIR / "yggdrasil_agents", v5 / "agents_and_lms" / "yggdrasil_agents")
    _copy_file(
        FOUNDRY_DIR / "modelfiles" / "Modelfile.yggdrasil-nano",
        v5 / "agents_and_lms" / "Modelfile.yggdrasil-nano",
    )
    _copy_file(FOUNDRY_DIR / "pyproject.toml", v5 / "agents_and_lms" / "pyproject.toml")

    app_v5 = v5 / "app-0.5.0"
    _copy_tree_clean(APP_DIR / "studio", app_v5 / "studio")
    _copy_file(APP_DIR / "YggdrasilStudio.pyw", app_v5 / "YggdrasilStudio.pyw")
    _copy_file(APP_DIR / "native_gui.py", app_v5 / "native_gui.py")
    _copy_file(APP_DIR / "YggdrasilDesktop.pyw", app_v5 / "YggdrasilDesktop.pyw")
    _copy_file(APP_DIR / "gui_app.py", app_v5 / "gui_app.py")
    _copy_file(APP_DIR / "app.py", app_v5 / "app.py")
    _copy_file(APP_DIR / "exported_nano_agents.py", app_v5 / "exported_nano_agents.py")
    _copy_file(APP_DIR / "dist_sync.py", app_v5 / "dist_sync.py")

    res_v5 = v5 / "resources"
    res_v5.mkdir(parents=True, exist_ok=True)
    (res_v5 / "tk_theme_tokens.json").write_text(tk_tokens_json, encoding="utf-8")
    (res_v5 / "nano_agents_manifest.json").write_text(manifest_json, encoding="utf-8")
    (res_v5 / "micro_model_1024_weights.json").write_text(weights_json, encoding="utf-8")
    (v5 / "logs").mkdir(parents=True, exist_ok=True)
    (v5 / "version").write_text("0.5.0\n", encoding="utf-8")
    (v5 / "YGGDRASIL_BUILD_INFO.txt").write_text(
        "Product: Yggdrasil Sovereign Studio\n"
        "Version: 0.5.0\n"
        "UI Runtime: Native PySide6 / Qt6 Gemini Interactive Workspace (Canvas, Deep Research, Gems, AGY SDK)\n"
        "Spec: SPEC-005\n",
        encoding="utf-8",
    )

    _copy_file(APP_DIR / "vaults" / "references.json", v5 / "data_and_vaults" / "references.json")
    _copy_file(APP_DIR / ".env.example", v5 / "data_and_vaults" / ".env.example")
    _init_vault_dbs(v5 / "data_and_vaults")
    v5_store = StudioStore(v5 / "data_and_vaults" / "studio.db")
    v5_store.seed_defaults_if_empty()
    v5_store.close()

    _copy_file(REPO_ROOT / "AGENTS.md", v5 / "markdowns_and_specs" / "AGENTS.md")
    _copy_file(REPO_ROOT / "PROJECT_STATE.md", v5 / "markdowns_and_specs" / "PROJECT_STATE.md")
    _copy_tree_clean(REPO_ROOT / "02-yggdrasil-lab" / "specs", v5 / "markdowns_and_specs" / "specs")
    _copy_file(
        REPO_ROOT / "01-code-oracle" / "001-nano-routing-and-deterministic-tools-grounding.md",
        v5 / "markdowns_and_specs" / "001-nano-routing-and-deterministic-tools-grounding.md",
    )
    _populate_user_content(v5 / "user_content", manifest_json, weights_json)
    _write_v5_and_root_launchers(v5, output_root)

    (output_root / "README.md").write_text(
        "# Yggdrasil Sovereign Studio — Standalone Distributions\n\n"
        "- **Launch Version 5 (`v0.5.0` Gemini Interactive Workspace + Canvas + Deep Research + AGY SDK — Recommended):** Double-click `Yggdrasil.pyw` or run `Launch-Yggdrasil.bat` / `Launch-Yggdrasil.ps1`.\n"
        "- **Version 4 (`v0.4.0` Gemini-Clone PySide6 Desktop Studio):** Preserved under `Version 4\\` (`YggdrasilAppLauncher.bat`).\n"
        "- **Version 3 (`v0.3.0` Tkinter Native Desktop Backup):** Preserved under `Version 3\\` (`YggdrasilAppLauncher.bat`).\n"
        "- **Version 2 (`v0.2.0` Web Studio Prototype):** Preserved under `Version 2\\` (`Launch-Yggdrasil-Studio.bat`).\n"
        "- **Version 1 (`v0.1.0` Baseline Backup):** Preserved under `Version 1\\`.\n",
        encoding="utf-8",
    )

    return {
        "output_root": str(output_root),
        "version_1": str(v1),
        "version_2": str(v2),
        "version_3": str(v3),
        "version_4": str(v4),
        "version_5": str(v5),
        "v5_changelogs": sorted(p.name for p in (v5 / "Changelog").glob("*.md")),
        "v5_agents_count": len(list((v5 / "agents_and_lms" / "yggdrasil_agents").glob("*.py"))),
    }


if __name__ == "__main__":
    print(json.dumps(sync_output_distributions(), indent=2))
