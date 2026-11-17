"""Yggdrasil Sovereign Studio v0.3.0 — Non-Web Native Desktop Software (Tkinter/TTK).

Pure desktop application inspired by `PDF converter.pyw` and the Google Gemini desktop shell:
zero web browser, zero HTTP server, direct local execution of Yggdrasil micro-agents,
animated tk.Canvas W_i tree, conditional [/userinterface] gate, and Pro PDF + Smart Linker.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import glob
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, ClassVar

from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class DesktopPaths:
    """Resolved runtime paths for both standalone Version 3 and monorepo execution."""

    mode: str
    root_dir: Path
    agents_dir: Path
    vaults_dir: Path
    changelog_dir: Path
    markdowns_dir: Path
    resources_dir: Path
    logs_dir: Path
    user_content_dir: Path
    personal_vault_db: Path
    state_tree_db: Path
    references_json: Path


def resolve_desktop_paths() -> DesktopPaths:
    """Resolve standalone Version 3 layout (root or app-0.3.0/) vs monorepo layout."""
    script_dir = Path(__file__).resolve().parent
    candidates = [script_dir, script_dir.parent]
    for base in candidates:
        if (base / "agents_and_lms" / "yggdrasil_agents").is_dir():
            vaults_dir = base / "data_and_vaults"
            return DesktopPaths(
                mode="standalone",
                root_dir=base,
                agents_dir=base / "agents_and_lms",
                vaults_dir=vaults_dir,
                changelog_dir=base / "Changelog",
                markdowns_dir=base / "markdowns_and_specs",
                resources_dir=base / "resources",
                logs_dir=base / "logs",
                user_content_dir=base / "user_content",
                personal_vault_db=vaults_dir / "personal_vault.db",
                state_tree_db=vaults_dir / "state_tree.db",
                references_json=vaults_dir / "references.json",
            )

    repo_root = script_dir.parent
    vaults_dir = script_dir / "vaults"
    return DesktopPaths(
        mode="monorepo",
        root_dir=repo_root,
        agents_dir=repo_root / "03-agent-foundry",
        vaults_dir=vaults_dir,
        changelog_dir=repo_root / "Changelog",
        markdowns_dir=repo_root / "02-yggdrasil-lab" / "specs",
        resources_dir=script_dir / "resources",
        logs_dir=script_dir / "logs",
        user_content_dir=script_dir / "user_content",
        personal_vault_db=vaults_dir / "personal_vault.db",
        state_tree_db=vaults_dir / "state_tree.db",
        references_json=vaults_dir / "references.json",
    )


PATHS = resolve_desktop_paths()
if str(PATHS.agents_dir) not in sys.path:
    sys.path.insert(0, str(PATHS.agents_dir))

from yggdrasil_agents import (
    ContextNodeState,
    LocalEngine,
    LocalEngineConfig,
    NestedModelOrchestrator,
    OrchestratorConfig,
    PdfConverterInput,
    ReferenceEntry,
    SmartPdfInput,
    TrunkRouter,
    UiAgentInput,
    UiThemeSpec,
    UserInterfaceNestedAgent,
    build_native_tk_style_tokens,
    pdf_converter_function,
    pre_group_prompt,
    smart_pdf_handling_function,
)


def ensure_desktop_directories(paths: DesktopPaths = PATHS) -> None:
    """Ensure local vaults, logs, resources, and Antigravity-style user_content folders exist."""
    for sub in ("brain", "instructions", "exports", "workspaces"):
        (paths.user_content_dir / sub).mkdir(parents=True, exist_ok=True)
    for folder in (paths.vaults_dir, paths.changelog_dir, paths.resources_dir, paths.logs_dir):
        folder.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(paths.personal_vault_db) as conn:
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

    with sqlite3.connect(paths.state_tree_db) as conn:
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

    if not paths.references_json.exists():
        paths.references_json.write_text(
            json.dumps({"schema_version": "1.0", "references": []}, indent=2),
            encoding="utf-8",
        )


def log_desktop_event(message: str, paths: DesktopPaths = PATHS) -> None:
    """Append timestamped entry into Version 3 logs/yggdrasil_desktop.log."""
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = paths.logs_dir / "yggdrasil_desktop.log"
    line = f"[{datetime.now(UTC).isoformat()}] {message}\n"
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(line)


def load_reference_entries(paths: DesktopPaths = PATHS) -> list[ReferenceEntry]:
    """Load non-sensitive domain references from references.json."""
    if not paths.references_json.exists():
        return []
    raw = json.loads(paths.references_json.read_text(encoding="utf-8"))
    items = raw.get("references", []) if isinstance(raw, dict) else []
    return [ReferenceEntry.model_validate(item) for item in items if isinstance(item, dict)]


def _drive_async(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except OSError:
        try:
            return coro.send(None)
        except StopIteration as stop:
            return stop.value


class SmartPdfWorkbenchEngine:
    """Pure-Python + LibreOffice + pypdf converter, numeric sorter & smart cross-linker."""

    SUPPORTED_EXTENSIONS: ClassVar[dict[str, tuple[str, ...]]] = {
        "All Office & PDF": (".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls"),
        "PDF Documents": (".pdf",),
        "PowerPoint": (".pptx", ".ppt"),
        "Word": (".docx", ".doc"),
        "Excel": (".xlsx", ".xls"),
    }

    @staticmethod
    def extract_numbers_from_filename(filename: str) -> list[int]:
        """Extract all integer sequences from a filename (matching PDF converter.pyw)."""
        return [int(tok) for tok in re.findall(r"\d+", filename)]

    @classmethod
    def smart_sort_files(cls, file_paths: list[str]) -> list[str]:
        """Sort files ascending by first extracted number, placing unnumbered files last."""
        keyed: list[tuple[bool, int, str, str]] = []
        for path in file_paths:
            name = os.path.basename(path)
            nums = cls.extract_numbers_from_filename(name)
            first = nums[0] if nums else 0
            has_num = len(nums) > 0
            keyed.append((not has_num, first, name.lower(), path))
        keyed.sort()
        return [item[3] for item in keyed]

    @staticmethod
    def find_libreoffice() -> str | None:
        """Detect LibreOffice soffice executable for Office-to-PDF conversion."""
        if sys.platform == "win32":
            candidates = [
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                r"C:\Program Files\LibreOffice*\program\soffice.exe",
                os.path.expanduser(r"~\AppData\Local\Programs\LibreOffice\program\soffice.exe"),
            ]
            for pattern in candidates:
                if "*" in pattern:
                    matches = glob.glob(pattern)
                    if matches:
                        return matches[0]
                elif os.path.exists(pattern):
                    return pattern
            return shutil.which("soffice")
        return shutil.which("libreoffice") or shutil.which("soffice")

    @staticmethod
    def _next_available_path(target_path: Path) -> Path:
        if not target_path.exists():
            return target_path
        stem = target_path.stem
        suffix = target_path.suffix
        counter = 1
        while True:
            candidate = target_path.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    @classmethod
    def convert_and_merge_files(
        cls,
        file_paths: list[str],
        output_folder: Path,
        *,
        combine_pdfs: bool = True,
        combined_filename: str = "Combined_Documents.pdf",
        sort_by_numbers: bool = True,
        smart_link_query: str | None = None,
        progress_cb: Any = None,
    ) -> dict[str, Any]:
        """Convert Office docs (when LibreOffice installed), merge PDFs, and run smart linking."""
        output_folder.mkdir(parents=True, exist_ok=True)
        ordered = cls.smart_sort_files(file_paths) if sort_by_numbers else list(file_paths)
        libreoffice = cls.find_libreoffice()

        temp_dir = Path(tempfile.mkdtemp(prefix="ygg_pdf_"))
        converted_pdfs: list[Path] = []
        failed_files: list[str] = []

        try:
            total = max(len(ordered), 1)
            for idx, raw_path in enumerate(ordered):
                if progress_cb is not None:
                    progress_cb(idx, total, os.path.basename(raw_path))
                src = Path(raw_path)
                ext = src.suffix.lower()
                if ext == ".pdf" and src.exists():
                    if combine_pdfs:
                        converted_pdfs.append(src)
                    else:
                        dest = cls._next_available_path(output_folder / src.name)
                        shutil.copy2(src, dest)
                        converted_pdfs.append(dest)
                    continue

                if libreoffice is None:
                    failed_files.append(f"{src.name} (LibreOffice required for {ext})")
                    continue

                target_dir = temp_dir if combine_pdfs else output_folder
                cmd = [
                    libreoffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(target_dir),
                    str(src),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
                out_pdf = target_dir / f"{src.stem}.pdf"
                if proc.returncode == 0 and out_pdf.exists():
                    converted_pdfs.append(out_pdf)
                else:
                    failed_files.append(src.name)

            if not converted_pdfs:
                return {
                    "successful": 0,
                    "total": len(ordered),
                    "combined_pdf": None,
                    "smart_index_path": None,
                    "failed": failed_files,
                    "cross_links_count": 0,
                    "pages_count": 0,
                }

            final_pdf_path: Path | None = None
            if combine_pdfs:
                clean_name = (
                    combined_filename
                    if combined_filename.lower().endswith(".pdf")
                    else f"{combined_filename}.pdf"
                )
                final_pdf_path = cls._next_available_path(output_folder / clean_name)
                writer = PdfWriter()
                for pdf_file in converted_pdfs:
                    reader = PdfReader(str(pdf_file), strict=False)
                    if len(reader.pages) > 0:
                        writer.append(str(pdf_file))
                writer.add_metadata(
                    {
                        "/Title": final_pdf_path.stem,
                        "/Producer": "Yggdrasil Sovereign Studio v0.3.0 (Smart PDF Workbench)",
                        "/Creator": "yggdrasil_agents.smart_pdf_handling_function",
                    }
                )
                with final_pdf_path.open("wb") as handle:
                    writer.write(handle)
                analysis_target = final_pdf_path
            else:
                analysis_target = converted_pdfs[0]

            # Deterministic 0-token PDF extraction & BM25/W_i smart cross-page linking.
            conv_out = pdf_converter_function(
                PdfConverterInput(
                    slice_id="desktop-pdf-conv",
                    source_path=str(analysis_target),
                    contains_personal_vault_data=True,
                )
            )
            smart_out = None
            smart_index_path: Path | None = None
            if conv_out.converted_pages:
                smart_out = smart_pdf_handling_function(
                    SmartPdfInput(
                        slice_id="desktop-pdf-smart",
                        pages=conv_out.converted_pages,
                        source_path=str(analysis_target),
                        query=smart_link_query or None,
                        contains_personal_vault_data=True,
                    )
                )
                smart_index_path = analysis_target.with_name(
                    f"{analysis_target.stem}_smart_index.json"
                )
                smart_index_path.write_text(
                    json.dumps(
                        {
                            "source_pdf": str(analysis_target),
                            "total_pages": conv_out.total_pages,
                            "detected_dois": conv_out.detected_dois,
                            "smart_pdf": smart_out.model_dump(mode="json"),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            if progress_cb is not None:
                progress_cb(total, total, "Complete")

            return {
                "successful": len(converted_pdfs),
                "total": len(ordered),
                "combined_pdf": str(final_pdf_path) if final_pdf_path else None,
                "smart_index_path": str(smart_index_path) if smart_index_path else None,
                "failed": failed_files,
                "cross_links_count": len(smart_out.cross_links) if smart_out else 0,
                "pages_count": conv_out.total_pages,
                "detected_dois": conv_out.detected_dois,
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def execute_studio_prompt(
    prompt: str,
    *,
    from_personal_vault: bool = True,
    user_confirmed_ui_handoff: bool = False,
    paths: DesktopPaths = PATHS,
) -> dict[str, Any]:
    """Run conditional [/userinterface] check and pre-grouped deterministic/nano dispatch."""
    ensure_desktop_directories(paths)
    ui_agent = UserInterfaceNestedAgent()
    ui_result = ui_agent.evaluate_or_execute(
        UiAgentInput(
            request_id=f"ui-{int(datetime.now(UTC).timestamp())}",
            raw_instruction=prompt,
            user_confirmed_handoff=user_confirmed_ui_handoff,
        )
    )
    if ui_result.status == "handoff_confirmation_required":
        return {"kind": "ui_handoff_required", "ui_result": ui_result.model_dump(mode="json")}

    bundle = pre_group_prompt(
        raw_text=prompt,
        source_id="yggdrasil_desktop_v3",
        from_personal_vault=from_personal_vault,
    )
    orchestrator = NestedModelOrchestrator(
        config=OrchestratorConfig(
            nano_model_name=os.getenv("YGGDRASIL_LOCAL_MODEL", "yggdrasil-nano"),
            references_json_path=str(paths.references_json),
        )
    )
    report = _drive_async(
        orchestrator.process_bundle(bundle=bundle, local_references=load_reference_entries(paths))
    )
    payload = {
        "kind": "executed",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "ui_result": ui_result.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
    }
    (paths.user_content_dir / "brain" / "last_desktop_session.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    log_desktop_event(
        f"Studio dispatch slices={report.total_slices} det_hits={report.deterministic_hits}",
        paths=paths,
    )
    return payload


class YggdrasilNativeDesktopApp:
    """True non-web Gemini-inspired Yggdrasil Sovereign Studio desktop software."""

    SETTINGS_FILE = Path.home() / ".yggdrasil_desktop_settings.json"
    PRESETS: ClassVar[dict[str, str]] = {
        "ChemEng Arrhenius + IMC PID": (
            "#CALC_SOLVE: Arrhenius\n"
            "mode=arrhenius\n"
            "1e8 * exp(-50000 / (8.31446261815324 * 350))\n"
            "[/#CALC_SOLVE]\n"
            "#CONTROL_SYSTEM: CSTR IMC PID\n"
            "kp=2.0 tau=10.0 theta=2.0 controller_type=PID tuning_method=imc imc_tau_c=2.0"
        ),
        "AST Code Optimiser": (
            "#CODE_OPTIMISE: Async QA Check\n"
            "import time\n"
            "async def poll():\n"
            "    time.sleep(1)\n"
            "    return 1"
        ),
        "Test GUI Keyword Handoff": "Adjust the GUI theme appearance and animation timing",
        "[/userinterface] Compact Theme": (
            "[/userinterface] Apply compact dark mode with fast animation"
        ),
    }

    def __init__(self, root: tk.Tk, paths: DesktopPaths = PATHS) -> None:
        self.root = root
        self.paths = paths
        ensure_desktop_directories(self.paths)
        self.theme = UiThemeSpec(ui_mode="native_desktop")
        self.tokens = build_native_tk_style_tokens(self.theme)

        self.root.title("Yggdrasil Sovereign Studio v0.3.0 — Desktop")
        self.root.geometry("1240x820")
        self.root.minsize(980, 680)
        self.root.configure(bg=self.tokens["bg_canvas"])

        self.settings = self._load_settings()
        self.pdf_files: list[str] = []
        self.sorted_pdf_files: list[str] = []
        self.converting = False
        self.last_combined_pdf: str | None = None
        self.libreoffice_path = SmartPdfWorkbenchEngine.find_libreoffice()
        self._anim_phase = 0.0
        self._views: dict[str, tk.Frame] = {}
        self._nav_buttons: dict[str, tk.Button] = {}
        self._tree_file_map: dict[str, Path] = {}

        self.vault_var = tk.BooleanVar(value=True)
        self.preset_var = tk.StringVar(value="ChemEng Arrhenius + IMC PID")
        self.filetype_var = tk.StringVar(value=self.settings.get("last_filetype", "All Office & PDF"))
        self.sort_by_numbers_var = tk.BooleanVar(value=bool(self.settings.get("sort_by_numbers", True)))
        self.output_folder_var = tk.StringVar(
            value=self.settings.get("output_folder", str(self.paths.user_content_dir / "exports"))
        )
        self.remember_output_var = tk.BooleanVar(value=True)
        self.combine_pdfs_var = tk.BooleanVar(value=bool(self.settings.get("combine_pdfs", True)))
        self.combined_name_var = tk.StringVar(
            value=self.settings.get("combined_filename", "Yggdrasil_Combined_Smart.pdf")
        )
        self.smart_query_var = tk.StringVar(value="IMC PID control kinetics Table 1")
        self.status_var = tk.StringVar(
            value=f"Ready ({self.paths.mode}) | Air-Gap Vault: LOCAL ONLY | 1K Micro-Router: 0 VRAM"
        )

        self._configure_ttk_styles()
        self._build_layout()
        self._bind_shortcuts()
        self.show_view("studio")
        self._animate_tree_step()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_settings(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "output_folder": str(self.paths.user_content_dir / "exports"),
            "combine_pdfs": True,
            "combined_filename": "Yggdrasil_Combined_Smart.pdf",
            "sort_by_numbers": True,
            "last_filetype": "All Office & PDF",
        }
        try:
            if self.SETTINGS_FILE.exists():
                loaded = json.loads(self.SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    defaults.update(loaded)
        except OSError:
            pass
        return defaults

    def _save_settings(self) -> None:
        self.settings.update(
            {
                "output_folder": self.output_folder_var.get(),
                "combine_pdfs": self.combine_pdfs_var.get(),
                "combined_filename": self.combined_name_var.get(),
                "sort_by_numbers": self.sort_by_numbers_var.get(),
                "last_filetype": self.filetype_var.get(),
            }
        )
        try:
            self.SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _configure_ttk_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        t = self.tokens
        style.configure("TFrame", background=t["bg_canvas"])
        style.configure("Surface.TFrame", background=t["bg_surface"])
        style.configure("TLabel", background=t["bg_canvas"], foreground=t["text_primary"], font=(t["font_ui"], 10))
        style.configure("Surface.TLabel", background=t["bg_surface"], foreground=t["text_primary"], font=(t["font_ui"], 10))
        style.configure("Muted.TLabel", background=t["bg_surface"], foreground=t["text_muted"], font=(t["font_ui"], 9))
        style.configure("TCheckbutton", background=t["bg_surface"], foreground=t["text_primary"], font=(t["font_ui"], 10))
        style.configure("TProgressbar", troughcolor=t["bg_surface_alt"], background=t["accent_primary"])
        style.configure(
            "Treeview",
            background=t["bg_surface"],
            fieldbackground=t["bg_surface"],
            foreground=t["text_primary"],
            rowheight=24,
        )

    def _build_layout(self) -> None:
        t = self.tokens
        # Top Gemini-inspired header bar
        header = tk.Frame(self.root, bg=t["bg_surface"], height=54, highlightthickness=1, highlightbackground=t["border"])
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        brand = tk.Label(
            header,
            text="  ✦  Yggdrasil Sovereign Studio",
            bg=t["bg_surface"],
            fg=t["accent_primary"],
            font=(t["font_title"], 14, "bold"),
        )
        brand.pack(side=tk.LEFT, padx=10)
        tk.Label(
            header,
            text="v0.3.0 Native Desktop",
            bg=t["bg_surface"],
            fg=t["text_muted"],
            font=(t["font_ui"], 10),
        ).pack(side=tk.LEFT)

        for badge_text, color in (
            ("[/userinterface] Gate: ARMED", t["accent_secondary"]),
            ("1K Micro-Router: 0 VRAM", t["accent_primary"]),
            ("Air-Gap Vault: LOCAL ONLY", t["accent_vault"]),
        ):
            tk.Label(
                header,
                text=badge_text,
                bg=t["bg_surface_alt"],
                fg=color,
                font=(t["font_ui"], 9, "bold"),
                padx=10,
                pady=4,
            ).pack(side=tk.RIGHT, padx=6, pady=10)

        # Body container: left nav rail + main view stack
        body = tk.Frame(self.root, bg=t["bg_canvas"])
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        rail = tk.Frame(body, bg=t["bg_surface"], width=230, highlightthickness=1, highlightbackground=t["border"])
        rail.pack(side=tk.LEFT, fill=tk.Y)
        rail.pack_propagate(False)

        tk.Label(
            rail,
            text="WORKSPACE",
            bg=t["bg_surface"],
            fg=t["text_muted"],
            font=(t["font_ui"], 9, "bold"),
        ).pack(anchor=tk.W, padx=16, pady=(16, 8))

        nav_items = (
            ("studio", "✦  Studio & Tag Dispatch"),
            ("pdf", "📄  Pro PDF & Smart Linker"),
            ("tree", "🌳  Live W_i Tree Canvas"),
            ("vaults", "📜  Changelogs & Vaults"),
        )
        for key, label in nav_items:
            btn = tk.Button(
                rail,
                text=label,
                anchor=tk.W,
                bg=t["bg_surface"],
                fg=t["text_primary"],
                activebackground=t["bg_surface_alt"],
                activeforeground=t["accent_primary"],
                relief=tk.FLAT,
                font=(t["font_ui"], 10),
                padx=14,
                pady=9,
                cursor="hand2",
                command=functools.partial(self.show_view, key),
            )
            btn.pack(fill=tk.X, padx=10, pady=3)
            self._nav_buttons[key] = btn

        lo_status = "✅ LibreOffice Ready" if self.libreoffice_path else "ℹ Pure-pypdf Mode (No LibreOffice)"
        tk.Label(
            rail,
            text=f"Mode: {self.paths.mode}\n{lo_status}",
            justify=tk.LEFT,
            bg=t["bg_surface"],
            fg=t["text_muted"],
            font=(t["font_ui"], 8),
        ).pack(side=tk.BOTTOM, anchor=tk.W, padx=14, pady=14)

        self.content_area = tk.Frame(body, bg=t["bg_canvas"])
        self.content_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=16, pady=14)

        self._build_studio_view()
        self._build_pdf_view()
        self._build_tree_view()
        self._build_vaults_view()

        status_bar = tk.Label(
            self.root,
            textvariable=self.status_var,
            anchor=tk.W,
            bg=t["bg_surface"],
            fg=t["text_muted"],
            font=(t["font_ui"], 9),
            padx=12,
            pady=5,
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def show_view(self, name: str) -> None:
        t = self.tokens
        for key, frame in self._views.items():
            if key == name:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()
        for key, btn in self._nav_buttons.items():
            is_active = key == name
            btn.configure(
                bg=t["bg_surface_alt"] if is_active else t["bg_surface"],
                fg=t["accent_primary"] if is_active else t["text_primary"],
            )
        if name == "vaults":
            self._refresh_vault_tree()

    def _build_studio_view(self) -> None:
        t = self.tokens
        frame = tk.Frame(self.content_area, bg=t["bg_canvas"])
        self._views["studio"] = frame

        hero = tk.Frame(frame, bg=t["bg_surface"], padx=18, pady=14, highlightthickness=1, highlightbackground=t["border"])
        hero.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            hero,
            text="Yggdrasil Sovereign Hybrid Studio",
            bg=t["bg_surface"],
            fg=t["accent_primary"],
            font=(t["font_title"], 16, "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            hero,
            text="Pre-grouped deterministic Python tools first (<1 ms, 0 LLM tokens) • Local yggdrasil-nano fallback • Air-gapped personal_vault.db",
            bg=t["bg_surface"],
            fg=t["text_muted"],
            font=(t["font_ui"], 9),
        ).pack(anchor=tk.W, pady=(3, 0))

        # Tag chips bar + preset selector
        chips_bar = tk.Frame(frame, bg=t["bg_canvas"])
        chips_bar.pack(fill=tk.X, pady=(0, 8))
        for tag in (
            "#TABLE_DATA",
            "#CALC_SOLVE",
            "#DATA_COMPARE",
            "#PDF_CONVERT",
            "#SMART_PDF_LINK",
            "#CODE_OPTIMISE",
            "#CONTROL_SYSTEM",
            "#RESEARCH_GAP",
            "[/userinterface]",
        ):
            fg = t["accent_secondary"] if tag == "[/userinterface]" else t["accent_primary"]
            tk.Button(
                chips_bar,
                text=tag,
                bg=t["bg_surface"],
                fg=fg,
                relief=tk.FLAT,
                font=(t["font_mono"], 8, "bold"),
                padx=8,
                pady=4,
                cursor="hand2",
                command=functools.partial(self._insert_studio_tag, tag),
            ).pack(side=tk.LEFT, padx=(0, 5))

        preset_row = tk.Frame(frame, bg=t["bg_canvas"])
        preset_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(preset_row, text="Preset:", bg=t["bg_canvas"], fg=t["text_muted"], font=(t["font_ui"], 9)).pack(side=tk.LEFT)
        combo = ttk.Combobox(
            preset_row,
            textvariable=self.preset_var,
            values=list(self.PRESETS.keys()),
            state="readonly",
            width=34,
        )
        combo.pack(side=tk.LEFT, padx=8)
        tk.Button(
            preset_row,
            text="Load Preset",
            bg=t["bg_surface_alt"],
            fg=t["text_primary"],
            relief=tk.FLAT,
            padx=10,
            pady=3,
            command=self._load_selected_preset,
        ).pack(side=tk.LEFT)

        self.studio_output = tk.Text(
            frame,
            height=14,
            bg=t["bg_surface"],
            fg=t["text_primary"],
            insertbackground=t["accent_primary"],
            font=(t["font_mono"], 10),
            relief=tk.FLAT,
            padx=12,
            pady=10,
            wrap=tk.WORD,
        )
        self.studio_output.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.studio_output.insert("1.0", "Ready. Choose a preset or paste tagged blocks and press Ctrl+Enter.\n")
        self.studio_output.configure(state=tk.DISABLED)

        composer = tk.Frame(frame, bg=t["bg_surface"], padx=12, pady=10, highlightthickness=1, highlightbackground=t["border"])
        composer.pack(fill=tk.X)
        self.prompt_text = tk.Text(
            composer,
            height=5,
            bg=t["bg_surface"],
            fg=t["text_primary"],
            insertbackground=t["accent_primary"],
            font=(t["font_mono"], 10),
            relief=tk.FLAT,
            wrap=tk.WORD,
        )
        self.prompt_text.pack(fill=tk.X)
        self.prompt_text.insert("1.0", self.PRESETS["ChemEng Arrhenius + IMC PID"])
        self.prompt_text.bind("<Control-Return>", lambda _e: self._run_studio_prompt())

        bar = tk.Frame(composer, bg=t["bg_surface"])
        bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(bar, text="Treat input as Air-Gapped Local Vault Context", variable=self.vault_var).pack(side=tk.LEFT)
        tk.Button(
            bar,
            text="▶ Execute Pipeline (Ctrl+Enter)",
            bg=t["accent_primary"],
            fg="#050811",
            font=(t["font_ui"], 10, "bold"),
            relief=tk.FLAT,
            padx=16,
            pady=6,
            cursor="hand2",
            command=self._run_studio_prompt,
        ).pack(side=tk.RIGHT)

    def _insert_studio_tag(self, tag: str) -> None:
        self.prompt_text.insert("1.0", f"{tag}: \n")
        self.prompt_text.focus_set()

    def _load_selected_preset(self) -> None:
        text = self.PRESETS.get(self.preset_var.get(), "")
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", text)

    def _set_studio_output(self, text: str) -> None:
        self.studio_output.configure(state=tk.NORMAL)
        self.studio_output.delete("1.0", tk.END)
        self.studio_output.insert("1.0", text)
        self.studio_output.configure(state=tk.DISABLED)

    def _run_studio_prompt(self, confirmed_handoff: bool = False) -> None:
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            return
        from_vault = self.vault_var.get()
        self.status_var.set("Running pre-grouped micro-router & deterministic solvers...")

        def _worker() -> None:
            result = execute_studio_prompt(
                prompt,
                from_personal_vault=from_vault,
                user_confirmed_ui_handoff=confirmed_handoff,
                paths=self.paths,
            )
            self.root.after(0, lambda: self._handle_studio_result(result))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_studio_result(self, result: dict[str, Any]) -> None:
        if result["kind"] == "ui_handoff_required":
            msg = result["ui_result"]["handoff_decision"]["handoff_prompt"]
            self._set_studio_output(f"[/userinterface] Conditional Gate Triggered:\n\n{msg}")
            if messagebox.askyesno("Hand Over to [/userinterface]?", msg):
                self._run_studio_prompt(confirmed_handoff=True)
            else:
                self.status_var.set("UI action held (user declined [/userinterface] handoff).")
            return

        self._set_studio_output(json.dumps(result, indent=2))
        rep = result["report"]
        self.status_var.set(
            f"Executed {rep['total_slices']} slice(s) | Deterministic hits: {rep['deterministic_hits']} | "
            f"Latency: {rep['total_latency_ms']:.2f} ms"
        )

    def _build_pdf_view(self) -> None:
        t = self.tokens
        frame = tk.Frame(self.content_area, bg=t["bg_canvas"])
        self._views["pdf"] = frame

        header = tk.Frame(frame, bg=t["bg_surface"], padx=16, pady=12, highlightthickness=1, highlightbackground=t["border"])
        header.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            header,
            text="📄 Pro PDF Converter, Numeric Sorter & Smart Cross-Page Linker",
            bg=t["bg_surface"],
            fg=t["accent_primary"],
            font=(t["font_title"], 14, "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            header,
            text="Inspired by PDF converter.pyw: extracts numbers to sort docs, converts Office/PDFs, merges with pypdf, and generates BM25 + W_i cross-page links.",
            bg=t["bg_surface"],
            fg=t["text_muted"],
            font=(t["font_ui"], 9),
        ).pack(anchor=tk.W, pady=(2, 0))

        # Step 1: File Queue Card
        q_card = tk.Frame(frame, bg=t["bg_surface"], padx=14, pady=12, highlightthickness=1, highlightbackground=t["border"])
        q_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        top_opts = tk.Frame(q_card, bg=t["bg_surface"])
        top_opts.pack(fill=tk.X, pady=(0, 8))
        tk.Label(top_opts, text="File Type:", bg=t["bg_surface"], fg=t["text_primary"], font=(t["font_ui"], 10, "bold")).pack(side=tk.LEFT)
        ttk.Combobox(
            top_opts,
            textvariable=self.filetype_var,
            values=list(SmartPdfWorkbenchEngine.SUPPORTED_EXTENSIONS.keys()),
            state="readonly",
            width=18,
        ).pack(side=tk.LEFT, padx=(8, 16))
        ttk.Checkbutton(
            top_opts,
            text="🔢 Sort files by numbers in filenames",
            variable=self.sort_by_numbers_var,
            command=self._refresh_pdf_listbox,
        ).pack(side=tk.LEFT)

        list_box_wrap = tk.Frame(q_card, bg=t["bg_surface"])
        list_box_wrap.pack(fill=tk.BOTH, expand=True)
        self.pdf_listbox = tk.Listbox(
            list_box_wrap,
            bg=t["bg_surface_alt"],
            fg=t["text_primary"],
            selectbackground=t["accent_primary"],
            selectforeground="#050811",
            font=(t["font_mono"], 9),
            height=8,
            relief=tk.FLAT,
        )
        self.pdf_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_box_wrap, orient=tk.VERTICAL, command=self.pdf_listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.pdf_listbox.configure(yscrollcommand=sb.set)

        btn_row = tk.Frame(q_card, bg=t["bg_surface"])
        btn_row.pack(fill=tk.X, pady=(8, 0))
        for txt, cmd in (
            ("📁 Add Files (Ctrl+O)", self._pdf_add_files),
            ("🔢 Sort Now (Ctrl+S)", self._pdf_sort_now),
            ("🗑️ Clear All (Esc)", self._pdf_clear_files),
            ("📂 Open Output (Ctrl+F)", self._pdf_open_output_folder),
            ("📄 Open PDF (Ctrl+P)", self._pdf_open_combined),
        ):
            tk.Button(
                btn_row,
                text=txt,
                bg=t["bg_surface_alt"],
                fg=t["text_primary"],
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2",
                command=cmd,
            ).pack(side=tk.LEFT, padx=(0, 8))

        # Step 2: Options Card
        opt_card = tk.Frame(frame, bg=t["bg_surface"], padx=14, pady=12, highlightthickness=1, highlightbackground=t["border"])
        opt_card.pack(fill=tk.X, pady=(0, 10))

        out_row = tk.Frame(opt_card, bg=t["bg_surface"])
        out_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(out_row, text="Output Folder:", bg=t["bg_surface"], fg=t["text_primary"], width=16, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(
            out_row,
            textvariable=self.output_folder_var,
            bg=t["bg_surface_alt"],
            fg=t["text_primary"],
            insertbackground=t["accent_primary"],
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=4)
        tk.Button(
            out_row,
            text="Browse (Ctrl+B)",
            bg=t["bg_surface_alt"],
            fg=t["text_primary"],
            relief=tk.FLAT,
            padx=10,
            pady=4,
            command=self._pdf_browse_output,
        ).pack(side=tk.LEFT)

        merge_row = tk.Frame(opt_card, bg=t["bg_surface"])
        merge_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            merge_row,
            text="Combine PDFs & generate Smart Cross-Page Index",
            variable=self.combine_pdfs_var,
        ).pack(side=tk.LEFT)
        tk.Label(merge_row, text="Filename:", bg=t["bg_surface"], fg=t["text_muted"]).pack(side=tk.LEFT, padx=(16, 6))
        tk.Entry(
            merge_row,
            textvariable=self.combined_name_var,
            bg=t["bg_surface_alt"],
            fg=t["text_primary"],
            relief=tk.FLAT,
            width=28,
        ).pack(side=tk.LEFT, ipady=3)

        query_row = tk.Frame(opt_card, bg=t["bg_surface"])
        query_row.pack(fill=tk.X)
        tk.Label(query_row, text="BM25 Link Query:", bg=t["bg_surface"], fg=t["text_primary"], width=16, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(
            query_row,
            textvariable=self.smart_query_var,
            bg=t["bg_surface_alt"],
            fg=t["text_primary"],
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        # Convert button + Progress
        action_row = tk.Frame(frame, bg=t["bg_canvas"])
        action_row.pack(fill=tk.X)
        self.pdf_run_btn = tk.Button(
            action_row,
            text="🚀 CONVERT, MERGE & SMART-LINK PDF (F5)",
            bg=t["accent_vault"],
            fg="#050811",
            font=(t["font_ui"], 11, "bold"),
            relief=tk.FLAT,
            padx=18,
            pady=9,
            cursor="hand2",
            command=self._pdf_start_conversion,
        )
        self.pdf_run_btn.pack(side=tk.LEFT)
        self.pdf_progress = ttk.Progressbar(action_row, mode="determinate")
        self.pdf_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 10))
        self.pdf_progress_label = tk.Label(action_row, text="Idle", bg=t["bg_canvas"], fg=t["text_muted"])
        self.pdf_progress_label.pack(side=tk.RIGHT)

    def _refresh_pdf_listbox(self) -> None:
        self.pdf_listbox.delete(0, tk.END)
        self.sorted_pdf_files = (
            SmartPdfWorkbenchEngine.smart_sort_files(self.pdf_files)
            if (self.sort_by_numbers_var.get() and self.pdf_files)
            else list(self.pdf_files)
        )
        for idx, file_path in enumerate(self.sorted_pdf_files, 1):
            name = os.path.basename(file_path)
            size_mb = (os.path.getsize(file_path) / (1024 * 1024)) if os.path.exists(file_path) else 0.0
            nums = SmartPdfWorkbenchEngine.extract_numbers_from_filename(name)
            prefix = "🔢" if (self.sort_by_numbers_var.get() and nums) else "  "
            num_info = f" [Numbers: {nums}]" if nums else " [No numbers]"
            self.pdf_listbox.insert(tk.END, f"{prefix} {idx:2d}. {name} ({size_mb:.2f} MB){num_info}")

    def _pdf_add_files(self) -> None:
        exts = SmartPdfWorkbenchEngine.SUPPORTED_EXTENSIONS.get(self.filetype_var.get(), (".pdf",))
        filter_str = " ".join(f"*{ext}" for ext in exts)
        selected = filedialog.askopenfilenames(
            title=f"Select {self.filetype_var.get()}",
            filetypes=[(self.filetype_var.get(), filter_str), ("All Files", "*.*")],
        )
        added = 0
        for p in selected:
            if p not in self.pdf_files:
                self.pdf_files.append(p)
                added += 1
        if added:
            self._refresh_pdf_listbox()
            self.status_var.set(f"Added {added} document(s) to Smart PDF Workbench.")

    def _pdf_sort_now(self) -> None:
        self._refresh_pdf_listbox()
        self.status_var.set("Sorted PDF queue by extracted filename numbers.")

    def _pdf_clear_files(self) -> None:
        if not self.converting:
            self.pdf_files.clear()
            self.sorted_pdf_files.clear()
            self.pdf_listbox.delete(0, tk.END)
            self.status_var.set("Cleared PDF queue.")

    def _pdf_browse_output(self) -> None:
        folder = filedialog.askdirectory(title="Select Output Folder", initialdir=self.output_folder_var.get())
        if folder:
            self.output_folder_var.set(folder)
            if self.remember_output_var.get():
                self._save_settings()

    def _pdf_open_output_folder(self) -> None:
        folder = self.output_folder_var.get()
        if folder and os.path.exists(folder) and sys.platform == "win32":
            os.startfile(folder)

    def _pdf_open_combined(self) -> None:
        if self.last_combined_pdf and os.path.exists(self.last_combined_pdf) and sys.platform == "win32":
            os.startfile(self.last_combined_pdf)
        else:
            messagebox.showinfo("No Combined PDF", "Run a merged conversion first (F5).")

    def _pdf_start_conversion(self) -> None:
        if self.converting:
            return
        if not self.pdf_files:
            messagebox.showwarning("No Files", "Add PDF or Office files first (Ctrl+O).")
            return
        if self.remember_output_var.get():
            self._save_settings()

        self.converting = True
        self.pdf_run_btn.configure(state=tk.DISABLED, text="⏳ Processing...")
        files_snapshot = list(self.pdf_files)
        out_dir = Path(self.output_folder_var.get())
        combine = self.combine_pdfs_var.get()
        combined_name = self.combined_name_var.get()
        sort_nums = self.sort_by_numbers_var.get()
        query = self.smart_query_var.get().strip() or None

        def _prog(cur: int, tot: int, label: str) -> None:
            def _ui() -> None:
                self.pdf_progress["maximum"] = max(tot, 1)
                self.pdf_progress["value"] = cur
                self.pdf_progress_label.configure(text=f"{cur}/{tot}: {label[:28]}")
            self.root.after(0, _ui)

        def _worker() -> None:
            summary = SmartPdfWorkbenchEngine.convert_and_merge_files(
                files_snapshot,
                out_dir,
                combine_pdfs=combine,
                combined_filename=combined_name,
                sort_by_numbers=sort_nums,
                smart_link_query=query,
                progress_cb=_prog,
            )
            self.root.after(0, lambda: self._pdf_done(summary))

        threading.Thread(target=_worker, daemon=True).start()

    def _pdf_done(self, summary: dict[str, Any]) -> None:
        self.converting = False
        self.pdf_run_btn.configure(state=tk.NORMAL, text="🚀 CONVERT, MERGE & SMART-LINK PDF (F5)")
        self.last_combined_pdf = summary.get("combined_pdf")
        log_desktop_event(f"PDF workbench completed: {summary}", paths=self.paths)
        if summary["successful"] > 0:
            self.status_var.set(
                f"PDF Complete: {summary['successful']}/{summary['total']} files, "
                f"{summary['pages_count']} pages, {summary['cross_links_count']} smart links"
            )
            messagebox.showinfo("Smart PDF Complete", json.dumps(summary, indent=2))
        else:
            messagebox.showerror("PDF Processing Failed", json.dumps(summary, indent=2))

    def _build_tree_view(self) -> None:
        t = self.tokens
        frame = tk.Frame(self.content_area, bg=t["bg_canvas"])
        self._views["tree"] = frame
        tk.Label(
            frame,
            text="🌳 Live Native Yggdrasil Context-Decay Tree (tk.Canvas — Zero WebView)",
            bg=t["bg_canvas"],
            fg=t["accent_primary"],
            font=(t["font_title"], 14, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))
        self.tree_canvas = tk.Canvas(
            frame,
            bg=t["bg_canvas"],
            highlightthickness=1,
            highlightbackground=t["border"],
        )
        self.tree_canvas.pack(fill=tk.BOTH, expand=True)

    def _animate_tree_step(self) -> None:
        self._anim_phase += 0.16
        canvas = self.tree_canvas
        w = max(canvas.winfo_width(), 780)
        h = max(canvas.winfo_height(), 460)
        canvas.delete("all")

        t = self.tokens
        cx, base_y = w // 2, h - 65
        canvas.create_line(cx, base_y, cx, 135, fill=t["accent_secondary"], width=10, capstyle=tk.ROUND)

        router = TrunkRouter(engine=LocalEngine.get_shared(LocalEngineConfig(model_name="yggdrasil-nano")))
        nodes = [
            ContextNodeState(node_id="n1", label="personal_vault.db", initial_weight=1.0, elapsed_hours=0.2, resonance_count=2, contains_personal_vault_data=True),
            ContextNodeState(node_id="n2", label="1K Micro-Router", initial_weight=0.95, elapsed_hours=0.1, resonance_count=3, contains_personal_vault_data=True),
            ContextNodeState(node_id="n3", label="8 Python Solvers", initial_weight=0.98, elapsed_hours=0.1, resonance_count=4, contains_personal_vault_data=False),
            ContextNodeState(node_id="n4", label="yggdrasil-nano", initial_weight=0.86, elapsed_hours=1.0, resonance_count=1, contains_personal_vault_data=False),
        ]
        pulse = 3.0 * math.sin(self._anim_phase)
        for idx, node in enumerate(nodes):
            dec = router.evaluate_node(node, allow_cloud=not node.contains_personal_vault_data)
            r = max(12.0, min(30.0, 12.0 + dec.weight * 8.5)) + pulse
            color = t["accent_vault"] if dec.air_gap_blocked else t["accent_primary"]
            nx = cx + (idx - 1.5) * 165.0
            ny = h - 140.0 if dec.air_gap_blocked else 105.0
            ay = base_y - 55 if dec.air_gap_blocked else 150
            canvas.create_line(cx, ay, nx, ny, fill=color, width=3, smooth=True)
            canvas.create_oval(nx - r, ny - r, nx + r, ny + r, fill=color, outline=t["bg_canvas"], width=2)
            canvas.create_text(
                nx,
                ny + r + 16,
                text=f"{node.label} (W={dec.weight:.2f})",
                fill=t["text_primary"],
                font=(t["font_ui"], 10, "bold"),
            )

        self.root.after(90, self._animate_tree_step)

    def _build_vaults_view(self) -> None:
        t = self.tokens
        frame = tk.Frame(self.content_area, bg=t["bg_canvas"])
        self._views["vaults"] = frame
        tk.Label(
            frame,
            text="📜 Versioned Changelogs, Specs, Vaults & User Content",
            bg=t["bg_canvas"],
            fg=t["accent_primary"],
            font=(t["font_title"], 14, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        split = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=t["bg_canvas"], sashwidth=6)
        split.pack(fill=tk.BOTH, expand=True)

        self.vault_tree = ttk.Treeview(split, show="tree")
        self.vault_tree.bind("<<TreeviewSelect>>", self._on_vault_tree_select)
        split.add(self.vault_tree, minsize=280)

        self.vault_viewer = tk.Text(
            split,
            bg=t["bg_surface"],
            fg=t["text_primary"],
            font=(t["font_mono"], 10),
            relief=tk.FLAT,
            padx=12,
            pady=10,
            wrap=tk.WORD,
        )
        split.add(self.vault_viewer, minsize=440)

    def _refresh_vault_tree(self) -> None:
        self.vault_tree.delete(*self.vault_tree.get_children())
        self._tree_file_map.clear()
        sections = (
            ("Changelog", self.paths.changelog_dir),
            ("Specs & Markdowns", self.paths.markdowns_dir),
            ("Data & Vaults", self.paths.vaults_dir),
            ("User Content", self.paths.user_content_dir),
            ("Resources", self.paths.resources_dir),
        )
        for label, base in sections:
            parent_id = self.vault_tree.insert("", tk.END, text=label, open=True)
            if not base.exists():
                continue
            for file_path in sorted(base.rglob("*")):
                if file_path.is_file() and "__pycache__" not in file_path.parts:
                    rel = str(file_path.relative_to(base))
                    node_id = self.vault_tree.insert(parent_id, tk.END, text=rel)
                    self._tree_file_map[node_id] = file_path

    def _on_vault_tree_select(self, _event: Any) -> None:
        sel = self.vault_tree.selection()
        if not sel:
            return
        file_path = self._tree_file_map.get(sel[0])
        if file_path is None or not file_path.exists():
            return
        if file_path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            content = (
                f"[Protected Binary SQLite Vault]\nPath: {file_path}\nSize: {file_path.stat().st_size} bytes\n"
                "Air-Gap Policy: personal_vault.db contents are strictly isolated on-device."
            )
        else:
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = f"[Binary file: {file_path.name} ({file_path.stat().st_size} bytes)]"
        self.vault_viewer.delete("1.0", tk.END)
        self.vault_viewer.insert("1.0", content)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self._pdf_add_files())
        self.root.bind("<Control-b>", lambda _e: self._pdf_browse_output())
        self.root.bind("<Control-s>", lambda _e: self._pdf_sort_now())
        self.root.bind("<Control-f>", lambda _e: self._pdf_open_output_folder())
        self.root.bind("<Control-p>", lambda _e: self._pdf_open_combined())
        self.root.bind("<F5>", lambda _e: self._pdf_start_conversion())
        self.root.bind("<Escape>", lambda _e: self._pdf_clear_files())

    def _on_close(self) -> None:
        self._save_settings()
        LocalEngine._instance = None
        self.root.destroy()


def run_desktop_self_test(paths: DesktopPaths = PATHS) -> dict[str, Any]:
    """Verify Version 3 native tokens, Smart PDF numeric sort/merge/link, and UI conditional gate."""
    ensure_desktop_directories(paths)
    tokens = build_native_tk_style_tokens(UiThemeSpec(ui_mode="native_desktop"))

    temp_dir = Path(tempfile.mkdtemp(prefix="ygg_v3_selftest_"))
    try:
        # Create 3 sample PDFs with out-of-order numbers to verify PDF converter.pyw sorting logic.
        for fname in ("Report_10_Appendix.pdf", "Report_2_Methods.pdf", "Report_Notes.pdf"):
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            with (temp_dir / fname).open("wb") as handle:
                writer.write(handle)

        raw_list = [
            str(temp_dir / "Report_10_Appendix.pdf"),
            str(temp_dir / "Report_2_Methods.pdf"),
            str(temp_dir / "Report_Notes.pdf"),
        ]
        sorted_names = [
            os.path.basename(p) for p in SmartPdfWorkbenchEngine.smart_sort_files(raw_list)
        ]
        out_dir = temp_dir / "merged_out"
        pdf_res = SmartPdfWorkbenchEngine.convert_and_merge_files(
            raw_list,
            out_dir,
            combine_pdfs=True,
            combined_filename="Test_Merged.pdf",
            sort_by_numbers=True,
            smart_link_query="Methods",
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    gate_blocked = execute_studio_prompt(
        "Update the GUI theme appearance",
        from_personal_vault=False,
        user_confirmed_ui_handoff=False,
        paths=paths,
    )
    gate_allowed = execute_studio_prompt(
        "[/userinterface] Apply compact dark mode\n"
        "#CALC_SOLVE: Add\n2 + 3 * 4\n[/#CALC_SOLVE]\n"
        "#CONTROL_SYSTEM: Loop\nkp=2.0 tau=10.0 theta=2.0",
        from_personal_vault=False,
        paths=paths,
    )
    LocalEngine._instance = None

    summary = {
        "mode": paths.mode,
        "ui_mode": "native_desktop",
        "script_path": str(Path(__file__).resolve()),
        "yggdrasil_agents_file": str(Path(sys.modules["yggdrasil_agents"].__file__ or "")),
        "tk_tokens_count": len(tokens),
        "smart_sorted_order": sorted_names,
        "pdf_merge_successful": pdf_res["successful"],
        "pdf_pages_count": pdf_res["pages_count"],
        "ui_gate_blocked_status": gate_blocked["ui_result"]["status"],
        "ui_gate_allowed_status": gate_allowed["ui_result"]["status"],
        "deterministic_hits": gate_allowed["report"]["deterministic_hits"],
    }
    (paths.user_content_dir / "brain" / "desktop_self_test.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    log_desktop_event("Completed desktop --self-test cleanly.", paths=paths)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yggdrasil Sovereign Studio v0.3.0 Native Desktop")
    parser.add_argument("--self-test", action="store_true", help="Run headless verification and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        print(json.dumps(run_desktop_self_test(PATHS), indent=2))
        return 0

    root = tk.Tk()
    YggdrasilNativeDesktopApp(root, paths=PATHS)
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = max(0, (root.winfo_screenwidth() // 2) - (w // 2))
    y = max(0, (root.winfo_screenheight() // 2) - (h // 2))
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
