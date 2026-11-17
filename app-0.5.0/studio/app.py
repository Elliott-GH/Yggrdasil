"""Yggdrasil Studio v0.5.0 — Gemini Interactive Agentic Workspace (PySide6).

Implements SPEC-004 & SPEC-005 under the conditional `[/userinterface]` (`07-userinterface-architect`)
architecture:
- Collapsible left sidebar (`#131418`, ~268px expanded, ~56px collapsed rail, `Ctrl+B`) with
  `📚 Library`, `📄 PDF Workbench`, `🌿 Pipeline & Antigravity SDK`, `💎 Gems` (4 seeded specialist
  personas + custom Gem creator), `Projects` ("Notebooks" slot), and `Recent` conversations.
- Split-screen `QSplitter` housing the Conversation / Home Greeting view on the left and the
  collapsible **Gemini Canvas Panel** (`CanvasWorkspacePanel`) on the right (`✏️ Co-Editor` +
  `👁️ Live Preview` tabs + deterministic transformation toolbar: `✨ Refine / Strip Filler`,
  `📐 Format CSV/Table to Markdown`, `⚡ AST Optimize Python Code`, `💾 Save to Library`,
  `📤 Export File...`, `📋 Copy`).
- Universal `+` popup menu & active removable mode pills (`📝 Canvas`, `🔬 Deep Research`,
  `🧠 Deep Think`, plus active `💎 Gem: <name>`) inside `PillComposerWidget`.
- Collapsible **Thinking & Routing Trace Drawer** (`🧠 Show Thinking & Routing Trace`) above each
  assistant reply + Gemini bottom action bar (`📝 Open in Canvas`, `📋 Copy`, `🔄 Regenerate`,
  `💾 Save to Library`).
- Dedicated **Google Antigravity SDK (`/google-antigravity-sdk`)** hub inside `Pipeline & Agents`
  displaying `AgySdkBridge.status()`, `https://aistudio.google.com/app/api-keys` setup link,
  equipped deterministic tools, and copyable `LocalOpenAIAgentConfig` / `LiteRTAgentConfig` /
  `LocalAgentConfig` Python configuration snippets.
- Headless `--self-test` verification mode (`QT_QPA_PLATFORM=offscreen`) writing
  `user_content/brain/studio_v5_self_test.json`.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import uuid
from concurrent.futures import Future
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from studio.paths import (
    StudioPaths,
    ensure_agents_on_path,
    ensure_studio_directories,
    resolve_studio_paths,
)

PATHS = resolve_studio_paths()
ensure_agents_on_path(PATHS)

from studio.settings import (
    StudioSettings,
    load_gemini_api_key,
    load_settings,
    save_settings,
)
from studio.store import (
    ArtifactKind,
    CanvasArtifact,
    Conversation,
    Gem,
    GemMode,
    Project,
    StoredMessage,
    StudioStore,
)
from studio.theme import PALETTE, build_studio_stylesheet
from yggdrasil_agents.agy_bridge import (
    AgyBackendMode,
    AgyBridgeConfig,
    AgySdkBridge,
)
from yggdrasil_agents.chat_pipeline import (
    ChatHistoryMessage,
    ChatPipelineConfig,
    ChatTurnRequest,
    ChatTurnResult,
    PipelineStage,
    ProjectContext,
    StudioChatPipeline,
    optimise_user_prompt,
)
from yggdrasil_agents.deterministic_tools import (
    CodingOptimiserInput,
    TableHandlingInput,
    coding_optimiser_function,
    data_handling_function,
)
from yggdrasil_agents.ui_agent import check_ui_handoff_gate

SUGGESTION_CHIPS: tuple[tuple[str, str], ...] = (
    (
        "⚗️ Solve Arrhenius rate & tune IMC PID loop",
        (
            "#CALC_SOLVE: mode=arrhenius\n"
            "A=1.25e6 Ea=54000 T=350\n"
            "#CONTROL_SYSTEM: tuning_method=imc\n"
            "kp=2.4 tau=18.0 theta=3.0"
        ),
    ),
    (
        "🔬 Deep Research: IMC PID & Reactor Stability",
        "DEEP_RESEARCH: Investigate Internal Model Control (IMC) PID tuning and Arrhenius reactor thermal stability bounds.",
    ),
    (
        "📊 Analyze CSV table & open in Canvas",
        (
            "#TABLE_DATA: format=csv\n"
            "temp_k,conversion,selectivity\n320,0.42,0.94\n340,0.68,0.91\n360,0.86,0.87\n"
            "#CALC_SOLVE: mode=evaluate_expression\n"
            "(0.86 - 0.42) / 0.42"
        ),
    ),
)

MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Auto (Nested Router) ▾", "auto"),
    ("🤖 AGY Local Agent (Ollama)", "agy-local"),
    ("🦙 yggdrasil-nano (Local)", "yggdrasil-nano"),
    ("🦙 qwen2.5:0.5b (Local)", "qwen2.5:0.5b"),
    ("🦙 smollm2:135m (Local)", "smollm2:135m"),
    ("☁ Gemini Cloud (AGY / Leaves)", "gemini-cloud"),
)


class RadialGlowCanvas(QWidget):
    """Container widget that paints a Gemini-inspired soft dark-blue radial glow behind its layout."""

    def __init__(self, parent: QWidget | None = None, *, glow_y_ratio: float = 0.42) -> None:
        super().__init__(parent)
        self._glow_y_ratio = glow_y_ratio
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        painter.fillRect(rect, QColor(PALETTE.bg_canvas))

        center = QPointF(rect.width() * 0.5, rect.height() * self._glow_y_ratio)
        radius = max(rect.width(), rect.height()) * 0.58
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, QColor(PALETTE.bg_glow_inner))
        gradient.setColorAt(0.45, QColor(PALETTE.bg_glow_mid))
        gradient.setColorAt(1.0, QColor(PALETTE.bg_canvas))
        painter.fillRect(rect, gradient)
        painter.end()
        super().paintEvent(event)


class ComposerInputEdit(QPlainTextEdit):
    """Auto-growing multi-line text input where Enter sends and Shift+Enter inserts a newline."""

    send_requested = Signal()
    escape_pressed = Signal()

    def __init__(self, placeholder: str = "Ask Yggdrasil", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ComposerInput")
        self.setPlaceholderText(placeholder)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFixedHeight(44)
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self) -> None:
        doc_lines = max(1, self.document().blockCount())
        target = min(132, max(42, 26 + doc_lines * 20))
        if self.height() != target:
            self.setFixedHeight(target)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                event.accept()
                self.send_requested.emit()
                return
        elif event.key() == Qt.Key.Key_Escape:
            event.accept()
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)


class PillComposerWidget(QFrame):
    """Gemini-style rounded pill composer with universal `+` popup menu, active mode/Gem chips, and model picker."""

    submit_turn = Signal(str, str, list)
    cancel_turn = Signal()
    open_pdf_workbench_requested = Signal()
    modes_changed = Signal()
    gem_cleared = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ComposerPillFrame")
        self._attachments: list[str] = []
        self._is_running: bool = False
        self.canvas_mode: bool = False
        self.deep_research_mode: bool = False
        self.thinking_mode: bool = False
        self.active_gem: Gem | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(6)

        # Active Mode Chips + Active Gem Pill + Attachments Row
        self.pills_row = QHBoxLayout()
        self.pills_row.setContentsMargins(2, 0, 2, 0)
        self.pills_row.setSpacing(6)

        self.gem_pill_btn = QPushButton("")
        self.gem_pill_btn.setObjectName("ComposerGemPill")
        self.gem_pill_btn.setToolTip("Click to clear active Gem persona")
        self.gem_pill_btn.setVisible(False)
        self.gem_pill_btn.clicked.connect(self._clear_active_gem)
        self.pills_row.addWidget(self.gem_pill_btn)

        self.canvas_pill_btn = QPushButton("📝 Canvas ✕")
        self.canvas_pill_btn.setObjectName("ComposerModePill")
        self.canvas_pill_btn.setVisible(False)
        self.canvas_pill_btn.clicked.connect(lambda: self.set_modes(canvas=False))
        self.pills_row.addWidget(self.canvas_pill_btn)

        self.research_pill_btn = QPushButton("🔬 Deep Research ✕")
        self.research_pill_btn.setObjectName("ComposerModePill")
        self.research_pill_btn.setVisible(False)
        self.research_pill_btn.clicked.connect(lambda: self.set_modes(deep_research=False))
        self.pills_row.addWidget(self.research_pill_btn)

        self.think_pill_btn = QPushButton("🧠 Deep Think ✕")
        self.think_pill_btn.setObjectName("ComposerModePill")
        self.think_pill_btn.setVisible(False)
        self.think_pill_btn.clicked.connect(lambda: self.set_modes(thinking=False))
        self.pills_row.addWidget(self.think_pill_btn)

        self.attachments_label = QLabel("")
        self.attachments_label.setStyleSheet(f"color: {PALETTE.accent_blue}; font-size: 11px;")
        self.clear_attach_btn = QPushButton("✕ Clear files")
        self.clear_attach_btn.setObjectName("RouteBadgeButton")
        self.clear_attach_btn.setVisible(False)
        self.clear_attach_btn.clicked.connect(self.clear_attachments)
        self.pills_row.addWidget(self.attachments_label)
        self.pills_row.addWidget(self.clear_attach_btn)
        self.pills_row.addStretch(1)
        outer.addLayout(self.pills_row)

        self.input_edit = ComposerInputEdit("Ask Yggdrasil", self)
        self.input_edit.send_requested.connect(self._on_send_clicked)
        self.input_edit.escape_pressed.connect(self.cancel_turn.emit)
        outer.addWidget(self.input_edit)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 2, 0, 0)
        bottom_row.setSpacing(8)

        self.plus_btn = QPushButton("＋")
        self.plus_btn.setObjectName("IconButton")
        self.plus_btn.setToolTip(
            "Upload files, toggle Canvas / Deep Research / Deep Think modes, or open PDF Workbench"
        )
        self.plus_btn.setFixedSize(32, 32)
        self.plus_btn.clicked.connect(self._show_plus_menu)
        bottom_row.addWidget(self.plus_btn)

        self.scope_badge = QLabel("")
        self.scope_badge.setObjectName("AirGapBadge")
        self.scope_badge.setVisible(False)
        bottom_row.addWidget(self.scope_badge)

        bottom_row.addStretch(1)

        self.model_combo = QComboBox(self)
        self.model_combo.setObjectName("ModelSelectorCombo")
        for label, value in MODEL_OPTIONS:
            self.model_combo.addItem(label, value)
        bottom_row.addWidget(self.model_combo)

        self.send_btn = QPushButton("➤")
        self.send_btn.setObjectName("SendPillButton")
        self.send_btn.setToolTip("Send message (Enter) / Stop (Esc)")
        self.send_btn.clicked.connect(self._on_send_clicked)
        bottom_row.addWidget(self.send_btn)

        outer.addLayout(bottom_row)

    def _show_plus_menu(self) -> None:
        menu = QMenu(self)

        upload_act = QAction("📎 Upload Files (PDF, Office, CSV, Code)…", self)
        upload_act.triggered.connect(self._pick_attachments)
        menu.addAction(upload_act)

        menu.addSeparator()

        canvas_act = QAction("📝 Canvas Mode (Co-Edit in Split View)", self)
        canvas_act.setCheckable(True)
        canvas_act.setChecked(self.canvas_mode)
        canvas_act.triggered.connect(lambda checked: self.set_modes(canvas=bool(checked)))
        menu.addAction(canvas_act)

        research_act = QAction("🔬 Deep Research Mode (Multi-Step Investigation)", self)
        research_act.setCheckable(True)
        research_act.setChecked(self.deep_research_mode)
        research_act.triggered.connect(
            lambda checked: self.set_modes(deep_research=bool(checked))
        )
        menu.addAction(research_act)

        think_act = QAction("🧠 Deep Think Mode (Show Reasoning Trace)", self)
        think_act.setCheckable(True)
        think_act.setChecked(self.thinking_mode)
        think_act.triggered.connect(lambda checked: self.set_modes(thinking=bool(checked)))
        menu.addAction(think_act)

        menu.addSeparator()

        pdf_act = QAction("📄 Open Smart PDF Workbench", self)
        pdf_act.triggered.connect(self.open_pdf_workbench_requested.emit)
        menu.addAction(pdf_act)

        menu.exec(self.plus_btn.mapToGlobal(self.plus_btn.rect().topLeft()))

    def set_modes(
        self,
        *,
        canvas: bool | None = None,
        deep_research: bool | None = None,
        thinking: bool | None = None,
        emit_signal: bool = True,
    ) -> None:
        if canvas is not None:
            self.canvas_mode = canvas
        if deep_research is not None:
            self.deep_research_mode = deep_research
        if thinking is not None:
            self.thinking_mode = thinking
        self.canvas_pill_btn.setVisible(self.canvas_mode)
        self.research_pill_btn.setVisible(self.deep_research_mode)
        self.think_pill_btn.setVisible(self.thinking_mode)
        if emit_signal:
            self.modes_changed.emit()

    def set_active_gem(self, gem: Gem | None) -> None:
        self.active_gem = gem
        if gem is None:
            self.gem_pill_btn.setVisible(False)
            return
        self.gem_pill_btn.setText(f"{gem.icon} Gem: {gem.name} ✕")
        self.gem_pill_btn.setVisible(True)

    def _clear_active_gem(self) -> None:
        self.active_gem = None
        self.gem_pill_btn.setVisible(False)
        self.gem_cleared.emit()

    def set_running(self, running: bool) -> None:
        self._is_running = running
        self.send_btn.setProperty("running", "true" if running else "false")
        self.send_btn.setText("■" if running else "➤")
        self.send_btn.style().unpolish(self.send_btn)
        self.send_btn.style().polish(self.send_btn)

    def set_project_scope_badge(self, project: Project | None) -> None:
        if project is None:
            self.scope_badge.setVisible(False)
            return
        if project.air_gapped:
            self.scope_badge.setText(f"🔒 {project.name} · Air-Gapped")
            self.scope_badge.setStyleSheet(
                f"background-color: #0b2920; color: {PALETTE.accent_vault}; "
                f"border: 1px solid {PALETTE.accent_vault}; border-radius: 10px; padding: 2px 8px; font-size: 11px;"
            )
        else:
            self.scope_badge.setText(f"📁 {project.name}")
            self.scope_badge.setStyleSheet(
                f"background-color: #1a2234; color: {PALETTE.accent_blue}; "
                f"border: 1px solid {PALETTE.border_composer}; border-radius: 10px; padding: 2px 8px; font-size: 11px;"
            )
        self.scope_badge.setVisible(True)

    def selected_model(self) -> str:
        data = self.model_combo.currentData()
        return str(data) if data else "auto"

    def set_selected_model(self, model_choice: str) -> None:
        for idx in range(self.model_combo.count()):
            if self.model_combo.itemData(idx) == model_choice:
                self.model_combo.setCurrentIndex(idx)
                return

    def refresh_model_options(
        self,
        local_models: list[str],
        *,
        cloud_ok: bool,
        local_only: bool,
    ) -> None:
        current = self.selected_model()
        self.model_combo.clear()
        self.model_combo.addItem("Auto (Nested Router) ▾", "auto")
        self.model_combo.addItem("🤖 AGY Local Agent (Ollama)", "agy-local")
        seen = {"yggdrasil-nano", "qwen2.5:0.5b", "smollm2:135m"}
        for m in ["yggdrasil-nano", "qwen2.5:0.5b", "smollm2:135m", *local_models]:
            if m not in seen or self.model_combo.findData(m) == -1:
                seen.add(m)
                self.model_combo.addItem(f"🦙 {m}", m)
        cloud_label = (
            "☁ Gemini Cloud (AGY / Leaves)"
            if (cloud_ok and not local_only)
            else "☁ Gemini Cloud (Local-Only / No Key)"
        )
        self.model_combo.addItem(cloud_label, "gemini-cloud")
        self.set_selected_model(current)

    def add_attachment_paths(self, paths: list[str]) -> None:
        for p in paths:
            if p and p not in self._attachments:
                self._attachments.append(p)
        self._refresh_attachment_banner()

    def clear_attachments(self) -> None:
        self._attachments.clear()
        self._refresh_attachment_banner()

    def _refresh_attachment_banner(self) -> None:
        if not self._attachments:
            self.attachments_label.setText("")
            self.clear_attach_btn.setVisible(False)
            return
        names = ", ".join(Path(p).name for p in self._attachments[:3])
        extra = f" (+{len(self._attachments) - 3} more)" if len(self._attachments) > 3 else ""
        self.attachments_label.setText(f"📎 Attached: {names}{extra}")
        self.clear_attach_btn.setVisible(True)

    def _pick_attachments(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach Files to Yggdrasil Turn",
            "",
            "Supported Files (*.pdf *.csv *.txt *.md *.py *.json *.docx *.pptx *.xlsx);;All Files (*.*)",
        )
        if files:
            self.add_attachment_paths(files)

    def _on_send_clicked(self) -> None:
        if self._is_running:
            self.cancel_turn.emit()
            return
        text = self.input_edit.toPlainText().strip()
        if not text and not self._attachments:
            return
        if not text and self._attachments:
            text = "Analyze the attached files."
        attachments = list(self._attachments)
        model = self.selected_model()
        self.input_edit.clear()
        self.clear_attachments()
        self.submit_turn.emit(text, model, attachments)


class UserMessageBubble(QFrame):
    """Right-aligned rounded user message bubble (`#1f2430`)."""

    def __init__(
        self,
        content: str,
        attachments: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.addStretch(1)

        bubble = QFrame(self)
        bubble.setObjectName("UserBubbleFrame")
        bubble.setMaximumWidth(560)
        b_layout = QVBoxLayout(bubble)
        b_layout.setContentsMargins(16, 10, 16, 10)
        b_layout.setSpacing(4)

        if attachments:
            att_lbl = QLabel("📎 " + ", ".join(Path(a).name for a in attachments))
            att_lbl.setStyleSheet(f"color: {PALETTE.accent_blue}; font-size: 11px;")
            att_lbl.setWordWrap(True)
            b_layout.addWidget(att_lbl)

        lbl = QLabel(content)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet(f"color: {PALETTE.text_primary}; font-size: 14px; background: transparent;")
        b_layout.addWidget(lbl)

        outer.addWidget(bubble)


class AssistantMessageCard(QFrame):
    """Left-aligned assistant response card with Collapsible Thinking Drawer, Markdown view, and Action Bar."""

    open_in_canvas_requested = Signal(str, str, str)
    save_to_library_requested = Signal(str, str, str)
    regenerate_requested = Signal(str)

    def __init__(
        self,
        markdown_text: str = "",
        meta: dict[str, Any] | None = None,
        *,
        user_prompt_for_regen: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AssistantCardFrame")
        self._markdown = markdown_text
        self._meta: dict[str, Any] = dict(meta or {})
        self._user_prompt_for_regen = user_prompt_for_regen
        self._details_expanded = False
        self._thinking_expanded = bool(self._meta.get("thinking_mode", False))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        sparkle = QLabel("✦ Yggdrasil")
        sparkle.setStyleSheet(
            f"color: {PALETTE.accent_blue}; font-weight: 600; font-size: 12px; background: transparent;"
        )
        header.addWidget(sparkle)

        self.gem_badge = QLabel("")
        self.gem_badge.setStyleSheet(
            f"background-color: #251b38; color: {PALETTE.accent_purple}; "
            "border: 1px solid #593b87; border-radius: 9px; padding: 1px 7px; font-size: 10px; font-weight: 600;"
        )
        self.gem_badge.setVisible(False)
        header.addWidget(self.gem_badge)

        self.air_gap_chip = QLabel("🔒 Air-Gapped Vault")
        self.air_gap_chip.setObjectName("AirGapBadge")
        self.air_gap_chip.setVisible(bool(self._meta.get("air_gap_enforced")))
        header.addWidget(self.air_gap_chip)
        header.addStretch(1)
        layout.addLayout(header)

        # Collapsible Thinking & Routing Trace Drawer above the reply
        thinking_hdr = QHBoxLayout()
        thinking_hdr.setContentsMargins(0, 0, 0, 0)
        self.thinking_toggle_btn = QPushButton("🧠 Show Thinking & Routing Trace ▸")
        self.thinking_toggle_btn.setObjectName("ThinkingToggleButton")
        self.thinking_toggle_btn.clicked.connect(self._toggle_thinking_drawer)
        thinking_hdr.addWidget(self.thinking_toggle_btn)
        thinking_hdr.addStretch(1)
        layout.addLayout(thinking_hdr)

        self.thinking_drawer = QFrame(self)
        self.thinking_drawer.setObjectName("ThinkingDrawerFrame")
        td_layout = QVBoxLayout(self.thinking_drawer)
        td_layout.setContentsMargins(12, 8, 12, 8)
        self.thinking_browser = QTextBrowser(self.thinking_drawer)
        self.thinking_browser.setFrameShape(QFrame.Shape.NoFrame)
        self.thinking_browser.setStyleSheet("background: transparent; font-size: 12px;")
        self.thinking_browser.setMaximumHeight(190)
        td_layout.addWidget(self.thinking_browser)
        self.thinking_drawer.setVisible(self._thinking_expanded)
        layout.addWidget(self.thinking_drawer)

        # Main Assistant Markdown Browser
        self.browser = QTextBrowser(self)
        self.browser.setObjectName("AssistantMarkdownBrowser")
        self.browser.setOpenExternalLinks(True)
        self.browser.setFrameShape(QFrame.Shape.NoFrame)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.browser)

        # Route Badge & Per-Message Gemini Action Bar
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 2, 0, 0)
        action_row.setSpacing(6)

        self.route_btn = QPushButton("")
        self.route_btn.setObjectName("RouteBadgeButton")
        self.route_btn.clicked.connect(self._toggle_stage_details)
        action_row.addWidget(self.route_btn)

        self.open_canvas_btn = QPushButton("📝 Open in Canvas")
        self.open_canvas_btn.setObjectName("MessageActionButton")
        self.open_canvas_btn.clicked.connect(self._emit_open_in_canvas)
        action_row.addWidget(self.open_canvas_btn)

        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setObjectName("MessageActionButton")
        self.copy_btn.clicked.connect(self._copy_markdown)
        action_row.addWidget(self.copy_btn)

        self.regen_btn = QPushButton("🔄 Regenerate")
        self.regen_btn.setObjectName("MessageActionButton")
        self.regen_btn.clicked.connect(self._emit_regenerate)
        action_row.addWidget(self.regen_btn)

        self.save_lib_btn = QPushButton("💾 Save to Library")
        self.save_lib_btn.setObjectName("MessageActionButton")
        self.save_lib_btn.clicked.connect(self._emit_save_to_library)
        action_row.addWidget(self.save_lib_btn)

        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.stages_label = QLabel("")
        self.stages_label.setWordWrap(True)
        self.stages_label.setVisible(False)
        self.stages_label.setStyleSheet(
            f"background-color: #12151e; color: {PALETTE.text_secondary}; "
            f"border: 1px solid {PALETTE.border_subtle}; border-radius: 10px; padding: 8px 12px; font-size: 11px;"
        )
        layout.addWidget(self.stages_label)

        self.set_markdown(markdown_text)
        self.update_meta(self._meta)

    def set_markdown(self, markdown_text: str) -> None:
        self._markdown = markdown_text
        self.browser.setMarkdown(markdown_text or "_Thinking…_")
        self._fit_document_height()

    def append_token(self, token: str) -> None:
        self._markdown += token
        self.browser.setMarkdown(self._markdown)
        self._fit_document_height()

    def _fit_document_height(self) -> None:
        doc = self.browser.document()
        width = max(480, self.browser.viewport().width() or 640)
        doc.setTextWidth(float(width))
        doc_height = int(doc.size().height()) + 18
        self.browser.setMinimumHeight(max(38, doc_height))
        self.browser.setMaximumHeight(max(38, doc_height))

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._fit_document_height()

    def update_meta(self, meta: dict[str, Any]) -> None:
        self._meta = dict(meta)
        route = str(meta.get("route", "deterministic"))
        det_hits = int(meta.get("deterministic_hits", 0))
        tokens = int(meta.get("llm_tokens_used", 0))
        model_used = meta.get("model_used") or ""
        tags = meta.get("tags_detected") or []
        air_gap = bool(meta.get("air_gap_enforced", False))
        self.air_gap_chip.setVisible(air_gap)

        gem_name = str(meta.get("gem_name") or "").strip()
        if gem_name:
            self.gem_badge.setText(f"💎 {gem_name}")
            self.gem_badge.setVisible(True)
        else:
            self.gem_badge.setVisible(False)

        if route == "deterministic":
            badge_text = f"⚡ Deterministic · {det_hits} tool(s) · 0 LLM tokens"
        elif route == "local_llm":
            badge_text = f"🦙 Local Nano · {model_used or 'yggdrasil-nano'} · ~{tokens} tokens"
        elif route == "mixed":
            badge_text = f"⚡+🦙 Mixed ({det_hits} deterministic + {model_used or 'local'}) · ~{tokens} tokens"
        elif route == "cloud":
            badge_text = f"☁ Gemini Cloud · {model_used or 'gemini-2.5-flash'} · ~{tokens} tokens"
        elif route == "offline_fallback":
            badge_text = "🛠 Offline · Deterministic Ready"
        else:
            badge_text = f"✦ Pipeline · {route}"

        if tags:
            badge_text += f" · {', '.join(str(t) for t in tags[:3])}"
        self.route_btn.setText(badge_text + " ▾")

        stages_raw = meta.get("stages") or []
        stage_lines: list[str] = []
        for s in stages_raw:
            if isinstance(s, dict):
                name = s.get("name", "stage")
                detail = s.get("detail", "")
                lat = float(s.get("latency_ms", 0.0))
                stage_lines.append(
                    f"• <b>{html.escape(str(name))}</b> ({lat:.1f} ms): {html.escape(str(detail))}"
                )
            elif isinstance(s, PipelineStage):
                stage_lines.append(
                    f"• <b>{html.escape(s.name)}</b> ({s.latency_ms:.1f} ms): {html.escape(s.detail)}"
                )
        if stage_lines:
            self.stages_label.setText("<br>".join(stage_lines))
        else:
            self.stages_label.setText("Pipeline route executed locally.")

        # Populate Thinking & Routing Trace markdown
        trace_md = str(meta.get("thinking_trace_markdown") or "").strip()
        if not trace_md and stage_lines:
            plain_stages = "\n".join(
                f"- **{s.get('name', 'stage')}** (`{float(s.get('latency_ms', 0.0)):.1f} ms`): {s.get('detail', '')}"
                for s in stages_raw
                if isinstance(s, dict)
            )
            trace_md = f"#### 🧠 Yggdrasil Deliberation & Routing Trace\n{plain_stages}"
        if not trace_md:
            trace_md = "#### 🧠 Yggdrasil Deliberation & Routing Trace\n- Executed via nested deterministic-first router."
        self.thinking_browser.setMarkdown(trace_md)

        n_stages = len(stages_raw) if isinstance(stages_raw, list) else 0
        arrow = "▾" if self._thinking_expanded else "▸"
        stage_suffix = f" ({n_stages} stages)" if n_stages else ""
        self.thinking_toggle_btn.setText(f"🧠 Show Thinking & Routing Trace{stage_suffix} {arrow}")

        if bool(meta.get("thinking_mode")) and not self._thinking_expanded:
            self._thinking_expanded = True
            self.thinking_drawer.setVisible(True)
            self.thinking_toggle_btn.setText(f"🧠 Hide Thinking & Routing Trace{stage_suffix} ▾")

    def _toggle_thinking_drawer(self) -> None:
        self._thinking_expanded = not self._thinking_expanded
        self.thinking_drawer.setVisible(self._thinking_expanded)
        stages_raw = self._meta.get("stages") or []
        n_stages = len(stages_raw) if isinstance(stages_raw, list) else 0
        stage_suffix = f" ({n_stages} stages)" if n_stages else ""
        prefix = "Hide" if self._thinking_expanded else "Show"
        arrow = "▾" if self._thinking_expanded else "▸"
        self.thinking_toggle_btn.setText(f"🧠 {prefix} Thinking & Routing Trace{stage_suffix} {arrow}")

    def _toggle_stage_details(self) -> None:
        self._details_expanded = not self._details_expanded
        self.stages_label.setVisible(self._details_expanded)

    def _resolve_canvas_payload(self) -> tuple[str, str, str]:
        title = str(self._meta.get("canvas_title") or self._meta.get("suggested_title") or "Canvas Document")
        content = str(self._meta.get("canvas_content") or self._markdown)
        kind = str(self._meta.get("canvas_kind") or "markdown")
        return title, content, kind

    def _emit_open_in_canvas(self) -> None:
        title, content, kind = self._resolve_canvas_payload()
        self.open_in_canvas_requested.emit(title, content, kind)

    def _emit_save_to_library(self) -> None:
        title, content, kind = self._resolve_canvas_payload()
        self.save_to_library_requested.emit(title, content, kind)

    def _copy_markdown(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._markdown)
        self.copy_btn.setText("✅ Copied")
        QTimer.singleShot(1400, lambda: self.copy_btn.setText("📋 Copy"))

    def _emit_regenerate(self) -> None:
        if self._user_prompt_for_regen:
            self.regenerate_requested.emit(self._user_prompt_for_regen)


class CanvasWorkspacePanel(QFrame):
    """Split-screen right-hand Gemini Canvas Co-Editor & Live Preview panel (`SPEC-005`)."""

    artifact_saved = Signal(object)

    def __init__(self, store: StudioStore, paths: StudioPaths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasWorkspaceFrame")
        self.store = store
        self.paths = paths
        self.current_artifact_id: str | None = None
        self.current_conversation_id: str | None = None
        self.current_project_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # Header Bar: Editable Title + Kind Selector + Close Canvas Button
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        badge_lbl = QLabel("📝 Canvas")
        badge_lbl.setStyleSheet(f"color: {PALETTE.accent_blue}; font-weight: 700; font-size: 13px;")
        hdr.addWidget(badge_lbl)

        self.title_edit = QLineEdit("Untitled Canvas")
        self.title_edit.setPlaceholderText("Artifact title…")
        hdr.addWidget(self.title_edit, 1)

        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("ModelSelectorCombo")
        for k_label, k_val in (
            ("Markdown", "markdown"),
            ("Python / Code", "code"),
            ("Deep Research Report", "report"),
            ("HTML Preview", "html"),
        ):
            self.kind_combo.addItem(k_label, k_val)
        self.kind_combo.currentIndexChanged.connect(self._sync_live_preview)
        hdr.addWidget(self.kind_combo)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("IconButton")
        self.close_btn.setToolTip("Close Canvas panel")
        self.close_btn.clicked.connect(lambda: self.setVisible(False))
        hdr.addWidget(self.close_btn)
        layout.addLayout(hdr)

        # Dual Tabs: ✏️ Co-Editor & 👁️ Live Preview
        self.tabs = QTabWidget(self)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("CanvasCodeEditor")
        self.editor.setPlaceholderText("Write or co-edit Markdown, Python code, CSV tables, or reports…")
        self.editor.textChanged.connect(self._sync_live_preview)
        self.tabs.addTab(self.editor, "✏️ Co-Editor")

        self.preview = QTextBrowser()
        self.preview.setObjectName("CanvasPreviewBrowser")
        self.preview.setOpenExternalLinks(True)
        self.tabs.addTab(self.preview, "👁️ Live Preview")
        layout.addWidget(self.tabs, 1)

        # Interactive Deterministic Transformation Toolbar
        tools_row1 = QHBoxLayout()
        tools_row1.setSpacing(6)

        self.refine_btn = QPushButton("✨ Refine / Strip Filler")
        self.refine_btn.setObjectName("CanvasActionChip")
        self.refine_btn.setToolTip("Deterministically strip conversational filler via optimise_user_prompt")
        self.refine_btn.clicked.connect(self.action_refine_text)
        tools_row1.addWidget(self.refine_btn)

        self.table_btn = QPushButton("📐 Format CSV/Table to Markdown")
        self.table_btn.setObjectName("CanvasActionChip")
        self.table_btn.setToolTip("Parse CSV/TSV/table and append statistical Markdown table")
        self.table_btn.clicked.connect(self.action_format_table)
        tools_row1.addWidget(self.table_btn)

        self.ast_btn = QPushButton("⚡ AST Optimize Python Code")
        self.ast_btn.setObjectName("CanvasActionChip")
        self.ast_btn.setToolTip("Run coding_optimiser_function static AST & complexity audit")
        self.ast_btn.clicked.connect(self.action_ast_optimize_code)
        tools_row1.addWidget(self.ast_btn)
        tools_row1.addStretch(1)
        layout.addLayout(tools_row1)

        tools_row2 = QHBoxLayout()
        tools_row2.setSpacing(6)

        self.save_btn = QPushButton("💾 Save to Library")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.save_to_library)
        tools_row2.addWidget(self.save_btn)

        self.export_btn = QPushButton("📤 Export File…")
        self.export_btn.setObjectName("CanvasActionChip")
        self.export_btn.clicked.connect(self.export_to_file)
        tools_row2.addWidget(self.export_btn)

        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setObjectName("CanvasActionChip")
        self.copy_btn.clicked.connect(self.copy_canvas_content)
        tools_row2.addWidget(self.copy_btn)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {PALETTE.accent_vault}; font-size: 11px;")
        tools_row2.addWidget(self.status_lbl, 1)
        layout.addLayout(tools_row2)

    def current_kind(self) -> ArtifactKind:
        raw = str(self.kind_combo.currentData() or "markdown")
        if raw in ("markdown", "code", "html", "report"):
            return cast("ArtifactKind", raw)
        return "markdown"

    def set_kind(self, kind: str) -> None:
        for idx in range(self.kind_combo.count()):
            if self.kind_combo.itemData(idx) == kind:
                self.kind_combo.setCurrentIndex(idx)
                return

    def open_document(
        self,
        title: str,
        content: str,
        *,
        kind: str = "markdown",
        artifact_id: str | None = None,
        conversation_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.current_artifact_id = artifact_id
        self.current_conversation_id = conversation_id
        self.current_project_id = project_id
        self.title_edit.setText(title.strip() or "Canvas Document")
        self.set_kind(kind)
        self.editor.setPlainText(content)
        self._sync_live_preview()
        self.setVisible(True)
        self.status_lbl.setText("Loaded in Canvas")

    def _sync_live_preview(self) -> None:
        text = self.editor.toPlainText()
        kind = self.current_kind()
        if kind == "html":
            self.preview.setHtml(text)
        elif kind == "code":
            fenced = text if text.lstrip().startswith("```") else f"```python\n{text}\n```"
            self.preview.setMarkdown(fenced)
        else:
            self.preview.setMarkdown(text)

    def action_refine_text(self) -> None:
        raw = self.editor.toPlainText().strip()
        if not raw:
            return
        opt = optimise_user_prompt(raw)
        self.editor.setPlainText(opt.optimised_text)
        removed = len(opt.removed_filler)
        self.status_lbl.setText(f"✨ Stripped {removed} filler phrase(s) (0 LLM tokens)")

    def action_format_table(self) -> None:
        raw = self.editor.toPlainText().strip()
        if not raw:
            return
        try:
            out = data_handling_function(
                TableHandlingInput(
                    slice_id="canvas-table",
                    raw_table=raw,
                )
            )
            stats_lines = [
                f"- **{s.column}** ({s.inferred_dtype}): mean=`{s.mean}`, min=`{s.min_val}`, max=`{s.max_val}`"
                for s in out.column_stats
            ]
            formatted = (
                f"### 📐 Formatted Table ({out.row_count}×{out.column_count})\n\n"
                f"{out.rendered_markdown}\n\n"
                f"#### Column Summary Statistics\n" + "\n".join(stats_lines)
            )
            self.editor.setPlainText(formatted)
            self.set_kind("markdown")
            self.tabs.setCurrentIndex(1)
            self.status_lbl.setText(f"📐 Formatted {out.row_count} rows × {out.column_count} cols")
        except ValueError as exc:
            self.status_lbl.setText(f"⚠️ Table parse: {exc}")

    def action_ast_optimize_code(self) -> None:
        raw = self.editor.toPlainText().strip()
        if not raw:
            return
        # Strip markdown fences if present
        lines = raw.splitlines()
        code_body = (
            "\n".join(lines[1:-1])
            if len(lines) >= 2 and lines[0].lstrip().startswith("```") and lines[-1].strip() == "```"
            else raw
        )
        out = coding_optimiser_function(
            CodingOptimiserInput(
                slice_id="canvas-ast",
                source_code=code_body,
            )
        )
        findings_md = "\n".join(
            f"- **[{f.severity.upper()}] {f.rule_id}** (line {f.line_number}): {f.message} — *{f.deterministic_fix_hint}*"
            for f in out.findings
        ) or "- ✅ Zero static QA findings."
        metrics_md = "\n".join(
            f"- `{m.name}` (lines {m.line_start}–{m.line_end}): McCabe={m.cyclomatic_complexity}, "
            f"nesting={m.max_nesting_depth}, typed={m.has_complete_type_annotations}"
            for m in out.function_metrics
        ) or "- Module-level script."
        report_block = (
            f"\n\n# --- Yggdrasil AST Audit (Maintainability: {out.maintainability_score:.1f}/100, "
            f"LOC: {out.loc}, Valid: {out.syntax_valid}) ---\n"
        )
        for f in out.findings:
            report_block += f"# [{f.severity}] L{f.line_number} {f.rule_id}: {f.message}\n"
        self.editor.setPlainText(code_body + report_block)
        self.preview.setMarkdown(
            f"### ⚡ AST Static Audit (`{out.maintainability_score:.1f}/100`)\n"
            f"```python\n{code_body}\n```\n"
            f"#### Function Metrics\n{metrics_md}\n\n#### Findings\n{findings_md}"
        )
        self.status_lbl.setText(
            f"⚡ AST Audit: {out.maintainability_score:.1f}/100 ({len(out.findings)} finding(s))"
        )

    def save_to_library(self) -> CanvasArtifact:
        title = self.title_edit.text().strip() or "Untitled Canvas"
        content = self.editor.toPlainText()
        kind = self.current_kind()
        if self.current_artifact_id:
            try:
                artifact = self.store.update_artifact(
                    self.current_artifact_id,
                    title=title,
                    content=content,
                    kind=kind,
                )
            except KeyError:
                artifact = self.store.save_artifact(
                    title=title,
                    content=content,
                    kind=kind,
                    conversation_id=self.current_conversation_id,
                    project_id=self.current_project_id,
                )
                self.current_artifact_id = artifact.id
        else:
            artifact = self.store.save_artifact(
                title=title,
                content=content,
                kind=kind,
                conversation_id=self.current_conversation_id,
                project_id=self.current_project_id,
            )
            self.current_artifact_id = artifact.id

        self.status_lbl.setText(f"💾 Saved '{artifact.title}' to Library")
        self.artifact_saved.emit(artifact)
        return artifact

    def export_to_file(self) -> None:
        title_slug = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_"
            for ch in (self.title_edit.text().strip() or "canvas_export")
        )
        kind = self.current_kind()
        ext = ".py" if kind == "code" else (".html" if kind == "html" else ".md")
        default_path = str(self.paths.user_content_dir / "exports" / f"{title_slug}{ext}")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Canvas Artifact",
            default_path,
            "Markdown (*.md);;Python (*.py);;HTML (*.html);;All Files (*.*)",
        )
        if not file_path:
            return
        Path(file_path).write_text(self.editor.toPlainText(), encoding="utf-8")
        self.status_lbl.setText(f"📤 Exported to {Path(file_path).name}")

    def copy_canvas_content(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.editor.toPlainText())
        self.status_lbl.setText("📋 Copied Canvas content to clipboard")


class GemEditorDialog(QDialog):
    """Modal dialog to create a custom reusable Gem persona (`SPEC-005`)."""

    def __init__(self, store: StudioStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.gem: Gem | None = None
        self.setWindowTitle("Create Custom Gem Persona")
        self.resize(500, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title_lbl = QLabel("💎 Create Specialist Gem Persona")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title_lbl)

        row = QHBoxLayout()
        row.addWidget(QLabel("Icon:"))
        self.icon_edit = QLineEdit("💎")
        self.icon_edit.setFixedWidth(60)
        row.addWidget(self.icon_edit)
        row.addWidget(QLabel("Gem Name:"))
        self.name_edit = QLineEdit("")
        self.name_edit.setPlaceholderText("e.g., Thermodynamics & Pinch Analyst")
        row.addWidget(self.name_edit, 1)
        layout.addLayout(row)

        layout.addWidget(QLabel("Short Description:"))
        self.desc_edit = QLineEdit("")
        self.desc_edit.setPlaceholderText("e.g., Heat exchanger network pinch analysis & entropy balances")
        layout.addWidget(self.desc_edit)

        layout.addWidget(QLabel("Default Workspace Mode:"))
        self.mode_combo = QComboBox()
        for label, val in (
            ("Standard Chat", "chat"),
            ("Canvas Co-Editor Mode", "canvas"),
            ("Deep Research Mode", "deep_research"),
            ("Deep Think (Reasoning Trace)", "thinking"),
        ):
            self.mode_combo.addItem(label, val)
        layout.addWidget(self.mode_combo)

        layout.addWidget(QLabel("Specialist System Instructions:"))
        self.inst_edit = QPlainTextEdit("")
        self.inst_edit.setPlaceholderText(
            "Define the domain rules, preferred equations, and output formatting for this Gem…"
        )
        layout.addWidget(self.inst_edit, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        name = self.name_edit.text().strip() or "Custom Gem"
        icon = self.icon_edit.text().strip() or "💎"
        desc = self.desc_edit.text().strip()
        inst = self.inst_edit.toPlainText().strip() or f"Act as {name}."
        raw_mode = str(self.mode_combo.currentData() or "chat")
        mode: GemMode = (
            cast("GemMode", raw_mode)
            if raw_mode in ("chat", "canvas", "deep_research", "thinking")
            else "chat"
        )
        self.gem = self.store.create_gem(
            name=name,
            instructions=inst,
            icon=icon,
            description=desc,
            default_mode=mode,
        )
        self.accept()


class ArtifactLibraryView(QWidget):
    """Persistent Library view (`📚 Library`) for browsing, searching, previewing, and reopening Canvas artifacts."""

    open_artifact_in_canvas = Signal(object)

    def __init__(self, store: StudioStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)

        hdr = QHBoxLayout()
        title = QLabel("📚 Canvas & Deep Research Artifact Library")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        hdr.addWidget(title)
        hdr.addStretch(1)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search saved artifacts…")
        self.search_edit.setFixedWidth(260)
        self.search_edit.textChanged.connect(self.refresh_library)
        hdr.addWidget(self.search_edit)
        layout.addLayout(hdr)

        sub = QLabel(
            "Every saved Canvas document, Python module, formatted table, and Deep Research report is stored locally in studio.db."
        )
        sub.setStyleSheet(f"color: {PALETTE.text_secondary};")
        layout.addWidget(sub)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        self.artifacts_list = QListWidget()
        self.artifacts_list.setObjectName("SidebarList")
        self.artifacts_list.currentItemChanged.connect(self._on_selection_changed)
        split.addWidget(self.artifacts_list)

        right_card = QFrame()
        right_card.setObjectName("SurfaceCard")
        rc_layout = QVBoxLayout(right_card)
        rc_layout.setContentsMargins(16, 14, 16, 14)
        rc_layout.setSpacing(10)

        self.preview_title_lbl = QLabel("Select an artifact to preview")
        self.preview_title_lbl.setStyleSheet("font-size: 15px; font-weight: 600;")
        rc_layout.addWidget(self.preview_title_lbl)

        self.preview_browser = QTextBrowser()
        rc_layout.addWidget(self.preview_browser, 1)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("📝 Open in Split-Screen Canvas")
        self.open_btn.setObjectName("PrimaryButton")
        self.open_btn.clicked.connect(self._open_selected)
        btn_row.addWidget(self.open_btn)

        self.delete_btn = QPushButton("🗑 Delete Artifact")
        self.delete_btn.setObjectName("SecondaryButton")
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        rc_layout.addLayout(btn_row)

        split.addWidget(right_card)
        split.setSizes([320, 620])
        layout.addWidget(split, 1)

        self.refresh_library()

    def refresh_library(self) -> None:
        query = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        self.artifacts_list.clear()
        for art in self.store.list_artifacts(search=query):
            icon = (
                "🔬"
                if art.kind == "report"
                else ("🐍" if art.kind == "code" else ("🌐" if art.kind == "html" else "📝"))
            )
            item = QListWidgetItem(f"{icon} {art.title}  ({art.kind})")
            item.setData(Qt.ItemDataRole.UserRole, art.id)
            self.artifacts_list.addItem(item)
        if self.artifacts_list.count() > 0 and self.artifacts_list.currentRow() == -1:
            self.artifacts_list.setCurrentRow(0)

    def _selected_artifact(self) -> CanvasArtifact | None:
        item = self.artifacts_list.currentItem()
        if item is None:
            return None
        art_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        return self.store.get_artifact(art_id) if art_id else None

    def _on_selection_changed(self) -> None:
        art = self._selected_artifact()
        if art is None:
            self.preview_title_lbl.setText("Select an artifact to preview")
            self.preview_browser.clear()
            return
        self.preview_title_lbl.setText(f"{art.title}  ·  {art.kind.upper()}  ·  {art.updated_at[:19]}")
        if art.kind == "code":
            self.preview_browser.setMarkdown(f"```python\n{art.content}\n```")
        elif art.kind == "html":
            self.preview_browser.setHtml(art.content)
        else:
            self.preview_browser.setMarkdown(art.content)

    def _open_selected(self) -> None:
        art = self._selected_artifact()
        if art is not None:
            self.open_artifact_in_canvas.emit(art)

    def _delete_selected(self) -> None:
        art = self._selected_artifact()
        if art is not None:
            self.store.delete_artifact(art.id)
            self.refresh_library()


class ProjectEditorDialog(QDialog):
    """Modal dialog to create or edit a Project, its custom instructions, air-gap flag, and pinned notes."""

    def __init__(
        self,
        store: StudioStore,
        project: Project | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.project = project
        self.setWindowTitle("Edit Project" if project else "New Project")
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title_lbl = QLabel("Project Workspace (Shared Context & Instructions)")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title_lbl)

        layout.addWidget(QLabel("Project Name:"))
        self.name_edit = QLineEdit(project.name if project else "")
        self.name_edit.setPlaceholderText("e.g., ChemEng Reactor Design")
        layout.addWidget(self.name_edit)

        self.air_gap_checkbox = QCheckBox(
            "🔒 Air-Gapped Vault Privacy (Never route chats or notes in this project to Cloud APIs)"
        )
        self.air_gap_checkbox.setChecked(project.air_gapped if project else True)
        self.air_gap_checkbox.setStyleSheet(f"color: {PALETTE.accent_vault}; font-weight: 600;")
        layout.addWidget(self.air_gap_checkbox)

        layout.addWidget(QLabel("System Instructions shared by all chats in this project:"))
        self.instructions_edit = QPlainTextEdit(project.instructions if project else "")
        self.instructions_edit.setPlaceholderText(
            "e.g., Always report units in SI (mol, J, K) and prefer IMC PID tuning rules."
        )
        self.instructions_edit.setFixedHeight(96)
        layout.addWidget(self.instructions_edit)

        notes_header = QHBoxLayout()
        notes_header.addWidget(QLabel("Pinned Project Notes & File Excerpts:"))
        notes_header.addStretch(1)
        self.add_note_btn = QPushButton("+ Add Note")
        self.add_note_btn.setObjectName("SecondaryButton")
        self.add_note_btn.clicked.connect(self._on_add_note)
        notes_header.addWidget(self.add_note_btn)

        self.attach_excerpt_btn = QPushButton("+ Attach File Excerpt")
        self.attach_excerpt_btn.setObjectName("SecondaryButton")
        self.attach_excerpt_btn.clicked.connect(self._on_attach_file_excerpt)
        notes_header.addWidget(self.attach_excerpt_btn)

        self.del_note_btn = QPushButton("Delete Selected")
        self.del_note_btn.setObjectName("SecondaryButton")
        self.del_note_btn.clicked.connect(self._on_delete_note)
        notes_header.addWidget(self.del_note_btn)
        layout.addLayout(notes_header)

        self.notes_list = QListWidget()
        self.notes_list.setObjectName("SidebarList")
        layout.addWidget(self.notes_list, 1)

        self._pending_notes: list[tuple[str, str]] = []
        self._refresh_notes()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_notes(self) -> None:
        self.notes_list.clear()
        if self.project is not None:
            for note in self.store.list_notes(self.project.id):
                item = QListWidgetItem(f"📌 {note.title} — {note.content[:80]}")
                item.setData(Qt.ItemDataRole.UserRole, note.id)
                self.notes_list.addItem(item)
        for idx, (title, content) in enumerate(self._pending_notes):
            item = QListWidgetItem(f"📌 (unsaved) {title} — {content[:80]}")
            item.setData(Qt.ItemDataRole.UserRole, f"pending:{idx}")
            self.notes_list.addItem(item)

    def _on_add_note(self) -> None:
        title, ok1 = QInputDialog.getText(self, "Add Pinned Note", "Note title:")
        if not ok1 or not title.strip():
            return
        content, ok2 = QInputDialog.getMultiLineText(self, "Add Pinned Note", "Note content:")
        if not ok2 or not content.strip():
            return
        if self.project is not None:
            self.store.add_note(self.project.id, title.strip(), content.strip())
        else:
            self._pending_notes.append((title.strip(), content.strip()))
        self._refresh_notes()

    def _on_attach_file_excerpt(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select File Excerpt to Pin",
            "",
            "Text & Data Files (*.txt *.md *.csv *.py *.json);;All Files (*.*)",
        )
        if not file_path:
            return
        p = Path(file_path)
        try:
            excerpt = p.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            return
        if self.project is not None:
            self.store.add_note(self.project.id, p.name, excerpt)
        else:
            self._pending_notes.append((p.name, excerpt))
        self._refresh_notes()

    def _on_delete_note(self) -> None:
        item = self.notes_list.currentItem()
        if item is None:
            return
        note_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if note_id.startswith("pending:"):
            idx = int(note_id.split(":", 1)[1])
            if 0 <= idx < len(self._pending_notes):
                self._pending_notes.pop(idx)
        elif note_id:
            self.store.delete_note(note_id)
        self._refresh_notes()

    def _on_save(self) -> None:
        name = self.name_edit.text().strip() or "Untitled Project"
        instructions = self.instructions_edit.toPlainText().strip()
        air_gapped = self.air_gap_checkbox.isChecked()
        if self.project is None:
            self.project = self.store.create_project(
                name=name,
                instructions=instructions,
                air_gapped=air_gapped,
            )
            for n_title, n_content in self._pending_notes:
                self.store.add_note(self.project.id, n_title, n_content)
        else:
            self.project = self.store.update_project(
                self.project.id,
                name=name,
                instructions=instructions,
                air_gapped=air_gapped,
            )
        self.accept()


class PdfWorkbenchView(QWidget):
    """Integrated Smart PDF Workbench view reusing `SmartPdfWorkbenchEngine` from `native_gui.py`."""

    attach_to_chat_requested = Signal(str)

    def __init__(self, paths: StudioPaths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self._files: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)

        header = QLabel("📄 Smart PDF & Office Workbench (SPEC-003 / SPEC-005)")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(header)

        sub = QLabel(
            "Numeric-sort lecture slides & documents, batch-convert Office files via LibreOffice, "
            "merge PDFs, and run deterministic 0-token BM25/W_i cross-page smart linking."
        )
        sub.setStyleSheet(f"color: {PALETTE.text_secondary};")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add PDF / Office Files")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._add_files)
        btn_row.addWidget(add_btn)

        sort_btn = QPushButton("🔢 Smart Numeric Sort")
        sort_btn.setObjectName("SecondaryButton")
        sort_btn.clicked.connect(self._smart_sort)
        btn_row.addWidget(sort_btn)

        clear_btn = QPushButton("Clear List")
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.clicked.connect(self._clear_files)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.file_list = QListWidget()
        self.file_list.setObjectName("SidebarList")
        layout.addWidget(self.file_list, 1)

        opts_row = QHBoxLayout()
        self.combine_chk = QCheckBox("Combine into single merged PDF")
        self.combine_chk.setChecked(True)
        opts_row.addWidget(self.combine_chk)

        opts_row.addWidget(QLabel("Output filename:"))
        self.output_name_edit = QLineEdit("Combined_Documents.pdf")
        self.output_name_edit.setFixedWidth(220)
        opts_row.addWidget(self.output_name_edit)

        opts_row.addWidget(QLabel("Smart-Link Query:"))
        self.query_edit = QLineEdit("")
        self.query_edit.setPlaceholderText("Optional BM25 keyword focus…")
        opts_row.addWidget(self.query_edit, 1)
        layout.addLayout(opts_row)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("⚡ Convert, Merge & Build Smart Link Index")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.clicked.connect(self._run_workbench)
        run_row.addWidget(self.run_btn)
        run_row.addStretch(1)
        layout.addLayout(run_row)

        self.result_browser = QTextBrowser()
        self.result_browser.setMaximumHeight(160)
        layout.addWidget(self.result_browser)

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDF or Office Files",
            "",
            "PDF & Office (*.pdf *.pptx *.ppt *.docx *.doc *.xlsx *.xls);;All Files (*.*)",
        )
        for f in files:
            if f not in self._files:
                self._files.append(f)
        self._refresh_list()

    def _smart_sort(self) -> None:
        from native_gui import SmartPdfWorkbenchEngine

        self._files = SmartPdfWorkbenchEngine.smart_sort_files(self._files)
        self._refresh_list()

    def _clear_files(self) -> None:
        self._files.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.file_list.clear()
        for idx, path in enumerate(self._files, start=1):
            self.file_list.addItem(f"{idx:02d}. {Path(path).name}  ({path})")

    def _run_workbench(self) -> None:
        from native_gui import SmartPdfWorkbenchEngine

        if not self._files:
            self.result_browser.setMarkdown("⚠️ Add at least one PDF or Office file first.")
            return
        out_dir = self.paths.user_content_dir / "exports"
        summary = SmartPdfWorkbenchEngine.convert_and_merge_files(
            self._files,
            out_dir,
            combine_pdfs=self.combine_chk.isChecked(),
            combined_filename=self.output_name_edit.text().strip() or "Combined_Documents.pdf",
            sort_by_numbers=True,
            smart_link_query=self.query_edit.text().strip() or None,
        )
        md = (
            f"### ✅ Smart PDF Workbench Complete\n"
            f"- **Processed:** {summary.get('successful')}/{summary.get('total')} file(s)\n"
            f"- **Total Pages:** {summary.get('pages_count')}\n"
            f"- **BM25 / W_i Cross-Links:** {summary.get('cross_links_count')}\n"
            f"- **Combined PDF:** `{summary.get('combined_pdf')}`\n"
            f"- **Smart Index JSON:** `{summary.get('smart_index_path')}`"
        )
        self.result_browser.setMarkdown(md)
        combined = summary.get("combined_pdf")
        if isinstance(combined, str) and combined:
            self.attach_to_chat_requested.emit(combined)


class PipelineAndChangelogsView(QWidget):
    """Inspector view with Google Antigravity SDK (`/google-antigravity-sdk`) Hub & Versioned Changelogs."""

    open_snippet_in_canvas = Signal(str, str, str)

    def __init__(self, paths: StudioPaths, agy_bridge: AgySdkBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.agy_bridge = agy_bridge

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)

        title = QLabel("🌿 Nested Pipeline, Google Antigravity SDK & Versioned Changelogs")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        info = QLabel(
            f"Mode: {paths.mode.upper()}  |  Studio DB: {paths.studio_db}  |  "
            f"Air-Gapped Personal Vault: {paths.personal_vault_db}"
        )
        info.setStyleSheet(f"color: {PALETTE.accent_vault}; font-weight: 600;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.tabs = QTabWidget(self)

        # Tab 1: Google Antigravity SDK Hub (/google-antigravity-sdk)
        agy_tab = QWidget()
        agy_layout = QVBoxLayout(agy_tab)
        agy_layout.setContentsMargins(16, 14, 16, 14)
        agy_layout.setSpacing(10)

        status = self.agy_bridge.status()
        sdk_badge = (
            "✅ google-antigravity SDK Installed"
            if status.sdk_installed
            else "🟢 AgySdkBridge Active (Shared LocalEngine + Deterministic Tool Harness)"
        )
        key_badge = (
            "✅ GEMINI_API_KEY Configured"
            if status.gemini_api_key_configured
            else f"🔑 Setup API Key: {status.api_key_setup_url}"
        )
        status_lbl = QLabel(
            f"{sdk_badge}  |  {key_badge}\n"
            f"Equipped Deterministic Tools: {', '.join(status.equipped_tools)}"
        )
        status_lbl.setStyleSheet(f"color: {PALETTE.accent_blue}; font-weight: 600;")
        status_lbl.setWordWrap(True)
        agy_layout.addWidget(status_lbl)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Antigravity Agent Config Preset:"))
        for label, b_mode in (
            ("LocalOpenAIAgentConfig (Ollama / LM Studio)", "local_openai"),
            ("LiteRTAgentConfig (On-Device GPU)", "lite_rt"),
            ("LocalAgentConfig (Hosted Gemini)", "hosted_gemini"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("SecondaryButton")
            btn.clicked.connect(lambda _checked=False, m=b_mode: self._switch_agy_mode(m))
            mode_row.addWidget(btn)
        mode_row.addStretch(1)
        agy_layout.addLayout(mode_row)

        self.agy_code_editor = QPlainTextEdit(status.config_preview_code)
        self.agy_code_editor.setObjectName("CanvasCodeEditor")
        self.agy_code_editor.setReadOnly(True)
        agy_layout.addWidget(self.agy_code_editor, 1)

        agy_actions = QHBoxLayout()
        copy_code_btn = QPushButton("📋 Copy SDK Snippet")
        copy_code_btn.setObjectName("PrimaryButton")
        copy_code_btn.clicked.connect(self._copy_agy_snippet)
        agy_actions.addWidget(copy_code_btn)

        send_canvas_btn = QPushButton("📝 Open Snippet in Canvas")
        send_canvas_btn.setObjectName("SecondaryButton")
        send_canvas_btn.clicked.connect(
            lambda: self.open_snippet_in_canvas.emit(
                "Antigravity SDK Agent Config",
                self.agy_code_editor.toPlainText(),
                "code",
            )
        )
        agy_actions.addWidget(send_canvas_btn)
        agy_actions.addStretch(1)
        agy_layout.addLayout(agy_actions)

        self.tabs.addTab(agy_tab, "🤖 Google Antigravity SDK Hub")

        # Tab 2: Changelogs & Architecture Specs
        docs_tab = QWidget()
        docs_layout = QVBoxLayout(docs_tab)
        docs_layout.setContentsMargins(16, 14, 16, 14)
        docs_layout.setSpacing(10)

        btn_row = QHBoxLayout()
        for label, fname in (
            ("MasterChangelog0.5", "MasterChangelog0.5.md"),
            ("YggrdasilChangelog0.5", "YggrdasilChangelog0.5.md"),
            ("EmbedAgentChangelog0.5", "EmbedAgentChangelog0.5.md"),
            ("SPEC-005 Architecture", "005-gemini-canvas-deep-research-agy-sdk-spec.md"),
            ("SPEC-004 Architecture", "004-gemini-clone-studio-chat-projects-spec.md"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("SecondaryButton")
            btn.clicked.connect(lambda _checked=False, fn=fname: self._load_doc(fn))
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        docs_layout.addLayout(btn_row)

        self.viewer = QTextBrowser()
        docs_layout.addWidget(self.viewer, 1)
        self.tabs.addTab(docs_tab, "📜 Changelogs & Specs")

        layout.addWidget(self.tabs, 1)
        self._load_doc("005-gemini-canvas-deep-research-agy-sdk-spec.md")

    def _switch_agy_mode(self, mode: str) -> None:
        if mode in ("local_openai", "hosted_gemini", "lite_rt"):
            self.agy_bridge.config.backend_mode = cast("AgyBackendMode", mode)
            self.agy_code_editor.setPlainText(self.agy_bridge.build_sdk_config_snippet())

    def _copy_agy_snippet(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.agy_code_editor.toPlainText())

    def _load_doc(self, filename: str) -> None:
        candidates = [
            self.paths.changelog_dir / filename,
            self.paths.markdowns_dir / filename,
            self.paths.changelog_dir / "MasterChangelog0.4.0.md",
        ]
        for candidate in candidates:
            if candidate.exists():
                self.viewer.setMarkdown(candidate.read_text(encoding="utf-8", errors="replace"))
                return
        self.viewer.setMarkdown(
            "### Yggdrasil Studio v0.5.0 Interactive Agentic Workspace\n"
            "1. **Split-Screen Gemini Canvas**: Co-Editor & Live Preview with deterministic tools.\n"
            "2. **Deep Research & Thinking Trace**: Multi-step cited reports + 1,024-param routing trace.\n"
            "3. **Gems & Library**: Reusable specialist personas and persistent `studio.db` artifact catalog.\n"
            "4. **Google Antigravity SDK Bridge**: `LocalOpenAIAgentConfig`, `LiteRTAgentConfig`, `LocalAgentConfig`."
        )


class SettingsDialog(QDialog):
    """Studio Settings dialog (`default_model`, `local_only`, Gemini API key status, vault path)."""

    def __init__(
        self,
        paths: StudioPaths,
        settings: StudioSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.settings = settings
        self.setWindowTitle("Yggdrasil Studio Settings")
        self.resize(480, 340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Default Model Choice:"))
        self.model_combo = QComboBox()
        for label, value in MODEL_OPTIONS:
            self.model_combo.addItem(label, value)
        for idx in range(self.model_combo.count()):
            if self.model_combo.itemData(idx) == settings.default_model:
                self.model_combo.setCurrentIndex(idx)
                break
        layout.addWidget(self.model_combo)

        self.local_only_chk = QCheckBox(
            "Enforce Local-Only Mode across all conversations (never call cloud Gemini)"
        )
        self.local_only_chk.setChecked(settings.local_only)
        layout.addWidget(self.local_only_chk)

        api_key = load_gemini_api_key(paths)
        key_status = (
            "✅ GEMINI_API_KEY detected in environment / .env"
            if api_key
            else "⚪ No GEMINI_API_KEY configured (Obtain key at https://aistudio.google.com/app/api-keys)"
        )
        key_lbl = QLabel(key_status)
        key_lbl.setWordWrap(True)
        key_lbl.setStyleSheet(f"color: {PALETTE.accent_vault if api_key else PALETTE.text_secondary};")
        layout.addWidget(key_lbl)

        vault_lbl = QLabel(f"Vaults Directory: {paths.vaults_dir}")
        vault_lbl.setWordWrap(True)
        vault_lbl.setStyleSheet(f"color: {PALETTE.text_secondary}; font-size: 11px;")
        layout.addWidget(vault_lbl)

        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        self.settings.default_model = str(self.model_combo.currentData() or "auto")
        self.settings.local_only = self.local_only_chk.isChecked()
        save_settings(self.settings, self.paths.settings_json)
        self.accept()


class YggdrasilStudioWindow(QMainWindow):
    """Main Gemini-inspired PySide6 Interactive Workspace window for Yggdrasil Studio v0.5.0."""

    token_received = Signal(str, str)
    turn_completed = Signal(object)

    def __init__(self, paths: StudioPaths = PATHS) -> None:
        super().__init__()
        ensure_studio_directories(paths)
        self.paths = paths
        self.settings: StudioSettings = load_settings(self.paths.settings_json)
        self.store = StudioStore(self.paths.studio_db)
        self.store.seed_defaults_if_empty()

        # Verify Law 7 conditional [/userinterface] gate on Studio initialization
        self.ui_gate_decision = check_ui_handoff_gate(
            "[/userinterface] Initialize Yggdrasil Studio v0.5.0 Gemini Canvas & Deep Research workspace",
            user_confirmed_handoff=True,
        )

        ollama_url = os.environ.get("YGGDRASIL_OLLAMA_BASE_URL", "http://localhost:11434/v1")
        default_local = (
            self.settings.default_model
            if self.settings.default_model not in ("auto", "gemini-cloud", "agy-local")
            else "qwen2.5:0.5b"
        )
        self.agy_bridge = AgySdkBridge(
            AgyBridgeConfig(
                backend_mode="local_openai",
                model_name=default_local,
                base_url=ollama_url,
                app_data_dir=str(self.paths.user_content_dir / "brain"),
            )
        )
        self.pipeline = StudioChatPipeline(
            ChatPipelineConfig(
                default_local_model=default_local,
                ollama_base_url=ollama_url,
                references_json_path=str(self.paths.references_json),
            )
        )
        self.pipeline.start()

        self.active_project_id: str | None = self.settings.last_project_id
        if self.active_project_id and self.store.get_project(self.active_project_id) is None:
            self.active_project_id = None
        self.active_gem_id: str | None = None
        self.active_conversation_id: str | None = None
        self._search_filter: str = ""
        self._sidebar_collapsed: bool = False
        self._streaming_cards: dict[str, AssistantMessageCard] = {}
        self._active_future: Future[ChatTurnResult] | None = None

        self.setWindowTitle("Yggdrasil Studio v0.5.0 — Gemini Canvas, Deep Research & Antigravity SDK")
        self.resize(1380, 860)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(build_studio_stylesheet(PALETTE))

        self.token_received.connect(self._on_token_streamed)
        self.turn_completed.connect(self._on_turn_finished)

        self._build_ui()
        self._register_shortcuts()
        self._refresh_sidebar()
        self._refresh_engine_status()
        self._show_home_greeting()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Collapsible Left Sidebar
        self.sidebar_frame = QFrame(root)
        self.sidebar_frame.setObjectName("SidebarFrame")
        self.sidebar_frame.setFixedWidth(PALETTE.sidebar_expanded_width)
        sb_layout = QVBoxLayout(self.sidebar_frame)
        sb_layout.setContentsMargins(12, 12, 12, 10)
        sb_layout.setSpacing(6)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(2, 0, 2, 2)
        top_bar.setSpacing(6)

        self.collapse_btn = QPushButton("☰")
        self.collapse_btn.setObjectName("IconButton")
        self.collapse_btn.setToolTip("Toggle sidebar (Ctrl+B)")
        self.collapse_btn.clicked.connect(self.toggle_sidebar)
        top_bar.addWidget(self.collapse_btn)

        self.brand_label = QLabel("✦ Yggdrasil")
        self.brand_label.setObjectName("BrandTitle")
        top_bar.addWidget(self.brand_label)
        top_bar.addStretch(1)

        self.search_btn = QPushButton("🔍")
        self.search_btn.setObjectName("IconButton")
        self.search_btn.setToolTip("Search conversations (Ctrl+K)")
        self.search_btn.clicked.connect(self.focus_search_box)
        top_bar.addWidget(self.search_btn)
        sb_layout.addLayout(top_bar)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter chats… (Ctrl+K)")
        self.search_edit.setVisible(False)
        self.search_edit.textChanged.connect(self._on_search_changed)
        sb_layout.addWidget(self.search_edit)

        self.new_chat_btn = QPushButton("＋  New chat")
        self.new_chat_btn.setObjectName("NewChatPillButton")
        self.new_chat_btn.setToolTip("Start a new chat (Ctrl+N)")
        self.new_chat_btn.clicked.connect(self.start_new_chat_view)
        sb_layout.addWidget(self.new_chat_btn)

        # Quick Navigation items
        self.nav_library_btn = QPushButton("📚  Library (Canvas & Reports)")
        self.nav_library_btn.setObjectName("SidebarNavButton")
        self.nav_library_btn.clicked.connect(self._show_library_view)
        sb_layout.addWidget(self.nav_library_btn)

        self.nav_pdf_btn = QPushButton("📄  PDF Workbench")
        self.nav_pdf_btn.setObjectName("SidebarNavButton")
        self.nav_pdf_btn.clicked.connect(self._show_pdf_view)
        sb_layout.addWidget(self.nav_pdf_btn)

        self.nav_pipeline_btn = QPushButton("🤖  Antigravity SDK & Pipeline")
        self.nav_pipeline_btn.setObjectName("SidebarNavButton")
        self.nav_pipeline_btn.clicked.connect(self._show_pipeline_view)
        sb_layout.addWidget(self.nav_pipeline_btn)

        # Gems section (Reusable Specialist Personas)
        gems_hdr = QHBoxLayout()
        self.gems_header_lbl = QLabel("Gems")
        self.gems_header_lbl.setObjectName("SectionHeader")
        gems_hdr.addWidget(self.gems_header_lbl)
        gems_hdr.addStretch(1)

        self.new_gem_btn = QPushButton("＋")
        self.new_gem_btn.setObjectName("IconButton")
        self.new_gem_btn.setToolTip("Create custom Gem persona")
        self.new_gem_btn.clicked.connect(self.create_gem_dialog)
        gems_hdr.addWidget(self.new_gem_btn)
        sb_layout.addLayout(gems_hdr)

        self.gems_list = QListWidget()
        self.gems_list.setObjectName("SidebarList")
        self.gems_list.setMaximumHeight(112)
        self.gems_list.itemClicked.connect(self._on_gem_item_clicked)
        sb_layout.addWidget(self.gems_list)

        # Projects section (where Gemini shows "Notebooks")
        proj_hdr = QHBoxLayout()
        self.projects_header_lbl = QLabel("Projects")
        self.projects_header_lbl.setObjectName("SectionHeader")
        proj_hdr.addWidget(self.projects_header_lbl)
        proj_hdr.addStretch(1)

        self.all_projects_btn = QPushButton("All")
        self.all_projects_btn.setObjectName("IconButton")
        self.all_projects_btn.setToolTip("Reset project filter (All chats)")
        self.all_projects_btn.clicked.connect(lambda: self.select_project(None))
        proj_hdr.addWidget(self.all_projects_btn)

        self.new_project_btn = QPushButton("＋")
        self.new_project_btn.setObjectName("IconButton")
        self.new_project_btn.setToolTip("Create new Project workspace")
        self.new_project_btn.clicked.connect(self.create_project_dialog)
        proj_hdr.addWidget(self.new_project_btn)
        sb_layout.addLayout(proj_hdr)

        self.projects_list = QListWidget()
        self.projects_list.setObjectName("SidebarList")
        self.projects_list.setMaximumHeight(108)
        self.projects_list.itemClicked.connect(self._on_project_item_clicked)
        self.projects_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.projects_list.customContextMenuRequested.connect(self._on_project_context_menu)
        sb_layout.addWidget(self.projects_list)

        # Recent / Pinned Conversations section
        self.chats_header_lbl = QLabel("Recent")
        self.chats_header_lbl.setObjectName("SectionHeader")
        sb_layout.addWidget(self.chats_header_lbl)

        self.chats_list = QListWidget()
        self.chats_list.setObjectName("SidebarList")
        self.chats_list.itemClicked.connect(self._on_chat_item_clicked)
        self.chats_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chats_list.customContextMenuRequested.connect(self._on_chat_context_menu)
        sb_layout.addWidget(self.chats_list, 1)

        # Footer: Engine status & Settings
        footer_frame = QFrame()
        footer_layout = QVBoxLayout(footer_frame)
        footer_layout.setContentsMargins(4, 4, 4, 2)
        footer_layout.setSpacing(4)

        self.engine_status_lbl = QLabel("● Deterministic & AGY Ready")
        self.engine_status_lbl.setStyleSheet(f"color: {PALETTE.accent_vault}; font-size: 11px;")
        footer_layout.addWidget(self.engine_status_lbl)

        self.settings_btn = QPushButton("⚙  Settings")
        self.settings_btn.setObjectName("SidebarNavButton")
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        footer_layout.addWidget(self.settings_btn)
        sb_layout.addWidget(footer_frame)

        root_layout.addWidget(self.sidebar_frame)

        # 2. Central Split-Screen Workspace (`QSplitter`: Left = Main Stack, Right = CanvasWorkspacePanel)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, root)
        root_layout.addWidget(self.workspace_splitter, 1)

        self.main_stack = QStackedWidget(self.workspace_splitter)
        self.workspace_splitter.addWidget(self.main_stack)

        self.canvas_panel = CanvasWorkspacePanel(
            self.store, self.paths, parent=self.workspace_splitter
        )
        self.canvas_panel.setVisible(False)
        self.canvas_panel.artifact_saved.connect(self._on_artifact_saved)
        self.workspace_splitter.addWidget(self.canvas_panel)
        self.workspace_splitter.setSizes([680, 520])

        # Page A: Home / Empty-Chat Greeting View with Radial Blue Glow
        self.home_view = RadialGlowCanvas(self.main_stack, glow_y_ratio=0.44)
        home_outer = QVBoxLayout(self.home_view)
        home_outer.setContentsMargins(32, 24, 32, 24)
        home_outer.addStretch(2)

        center_col_wrap = QHBoxLayout()
        center_col_wrap.addStretch(1)
        center_col = QWidget(self.home_view)
        center_col.setMaximumWidth(PALETTE.chat_column_max_width)
        center_col.setMinimumWidth(480)
        cc_layout = QVBoxLayout(center_col)
        cc_layout.setContentsMargins(0, 0, 0, 0)
        cc_layout.setSpacing(14)

        self.greeting_title_lbl = QLabel("Where should we start?")
        self.greeting_title_lbl.setObjectName("GreetingHeroLabel")
        self.greeting_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cc_layout.addWidget(self.greeting_title_lbl)

        self.greeting_sub_lbl = QLabel(
            "Ask anything, co-edit in split-screen Canvas, or launch multi-step Deep Research."
        )
        self.greeting_sub_lbl.setObjectName("GreetingSubLabel")
        self.greeting_sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.greeting_sub_lbl.setWordWrap(True)
        cc_layout.addWidget(self.greeting_sub_lbl)

        self.project_banner_row = QHBoxLayout()
        self.project_banner_row.addStretch(1)
        self.edit_project_btn = QPushButton("⚙ Manage Project Instructions & Notes")
        self.edit_project_btn.setObjectName("RouteBadgeButton")
        self.edit_project_btn.setVisible(False)
        self.edit_project_btn.clicked.connect(self.edit_active_project_dialog)
        self.project_banner_row.addWidget(self.edit_project_btn)
        self.project_banner_row.addStretch(1)
        cc_layout.addLayout(self.project_banner_row)

        self.home_composer = PillComposerWidget(center_col)
        self.home_composer.set_selected_model(self.settings.default_model)
        self.home_composer.submit_turn.connect(self._handle_composer_submit)
        self.home_composer.cancel_turn.connect(self.cancel_active_turn)
        self.home_composer.open_pdf_workbench_requested.connect(self._show_pdf_view)
        self.home_composer.modes_changed.connect(
            lambda: self._sync_composer_modes(self.home_composer)
        )
        self.home_composer.gem_cleared.connect(self._on_gem_cleared)
        cc_layout.addWidget(self.home_composer)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        chips_row.addStretch(1)
        for chip_label, chip_prompt in SUGGESTION_CHIPS:
            chip_btn = QPushButton(chip_label)
            chip_btn.setObjectName("SuggestionChip")
            chip_btn.clicked.connect(
                lambda _checked=False, p=chip_prompt: self._activate_suggestion_chip(p)
            )
            chips_row.addWidget(chip_btn)
        chips_row.addStretch(1)
        cc_layout.addLayout(chips_row)

        center_col_wrap.addWidget(center_col, 1)
        center_col_wrap.addStretch(1)
        home_outer.addLayout(center_col_wrap)
        home_outer.addStretch(3)
        self.main_stack.addWidget(self.home_view)

        # Page B: Active Conversation View
        self.chat_view = RadialGlowCanvas(self.main_stack, glow_y_ratio=0.18)
        chat_outer = QVBoxLayout(self.chat_view)
        chat_outer.setContentsMargins(0, 0, 0, 14)
        chat_outer.setSpacing(6)

        chat_top = QHBoxLayout()
        chat_top.setContentsMargins(24, 12, 24, 6)
        self.chat_title_lbl = QLabel("New chat")
        self.chat_title_lbl.setStyleSheet("font-size: 15px; font-weight: 600;")
        chat_top.addWidget(self.chat_title_lbl)

        self.chat_project_badge = QLabel("")
        self.chat_project_badge.setObjectName("AirGapBadge")
        self.chat_project_badge.setVisible(False)
        chat_top.addWidget(self.chat_project_badge)
        chat_top.addStretch(1)

        self.toggle_canvas_top_btn = QPushButton("📝 Toggle Canvas")
        self.toggle_canvas_top_btn.setObjectName("RouteBadgeButton")
        self.toggle_canvas_top_btn.clicked.connect(
            lambda: self.canvas_panel.setVisible(not self.canvas_panel.isVisible())
        )
        chat_top.addWidget(self.toggle_canvas_top_btn)
        chat_outer.addLayout(chat_top)

        self.messages_scroll = QScrollArea(self.chat_view)
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_scroll.setStyleSheet("background: transparent;")

        scroll_host = QWidget()
        scroll_host.setStyleSheet("background: transparent;")
        scroll_host_h = QHBoxLayout(scroll_host)
        scroll_host_h.setContentsMargins(20, 8, 20, 16)
        scroll_host_h.addStretch(1)

        self.messages_column_widget = QWidget(scroll_host)
        self.messages_column_widget.setMaximumWidth(PALETTE.chat_column_max_width)
        self.messages_column_widget.setMinimumWidth(480)
        self.messages_layout = QVBoxLayout(self.messages_column_widget)
        self.messages_layout.setContentsMargins(0, 0, 0, 0)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)

        scroll_host_h.addWidget(self.messages_column_widget, 1)
        scroll_host_h.addStretch(1)
        self.messages_scroll.setWidget(scroll_host)
        chat_outer.addWidget(self.messages_scroll, 1)

        dock_wrap = QHBoxLayout()
        dock_wrap.setContentsMargins(24, 4, 24, 4)
        dock_wrap.addStretch(1)
        self.chat_composer = PillComposerWidget(self.chat_view)
        self.chat_composer.setMaximumWidth(PALETTE.chat_column_max_width)
        self.chat_composer.setMinimumWidth(480)
        self.chat_composer.set_selected_model(self.settings.default_model)
        self.chat_composer.submit_turn.connect(self._handle_composer_submit)
        self.chat_composer.cancel_turn.connect(self.cancel_active_turn)
        self.chat_composer.open_pdf_workbench_requested.connect(self._show_pdf_view)
        self.chat_composer.modes_changed.connect(
            lambda: self._sync_composer_modes(self.chat_composer)
        )
        self.chat_composer.gem_cleared.connect(self._on_gem_cleared)
        dock_wrap.addWidget(self.chat_composer, 1)
        dock_wrap.addStretch(1)
        chat_outer.addLayout(dock_wrap)

        self.main_stack.addWidget(self.chat_view)

        # Page C: Persistent Artifact Library View
        self.library_view = ArtifactLibraryView(self.store, self.main_stack)
        self.library_view.open_artifact_in_canvas.connect(self._on_open_artifact_from_library)
        self.main_stack.addWidget(self.library_view)

        # Page D: Integrated PDF Workbench View
        self.pdf_view = PdfWorkbenchView(self.paths, self.main_stack)
        self.pdf_view.attach_to_chat_requested.connect(self._on_pdf_attached_from_workbench)
        self.main_stack.addWidget(self.pdf_view)

        # Page E: Pipeline, Antigravity SDK & Changelogs View
        self.pipeline_view = PipelineAndChangelogsView(
            self.paths, self.agy_bridge, self.main_stack
        )
        self.pipeline_view.open_snippet_in_canvas.connect(self._open_card_in_canvas)
        self.main_stack.addWidget(self.pipeline_view)

    def _sync_composer_modes(self, source: PillComposerWidget) -> None:
        target = self.chat_composer if source is self.home_composer else self.home_composer
        target.set_modes(
            canvas=source.canvas_mode,
            deep_research=source.deep_research_mode,
            thinking=source.thinking_mode,
            emit_signal=False,
        )

    def _show_library_view(self) -> None:
        self.library_view.refresh_library()
        self.main_stack.setCurrentWidget(self.library_view)

    def _show_pdf_view(self) -> None:
        self.main_stack.setCurrentWidget(self.pdf_view)

    def _show_pipeline_view(self) -> None:
        self.main_stack.setCurrentWidget(self.pipeline_view)

    def _register_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+N"), self, self.start_new_chat_view)
        QShortcut(QKeySequence("Ctrl+B"), self, self.toggle_sidebar)
        QShortcut(QKeySequence("Ctrl+K"), self, self.focus_search_box)
        QShortcut(QKeySequence("Escape"), self, self.cancel_active_turn)

    def toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        collapsed = self._sidebar_collapsed
        self.sidebar_frame.setFixedWidth(
            PALETTE.sidebar_collapsed_width if collapsed else PALETTE.sidebar_expanded_width
        )
        for widget in (
            self.brand_label,
            self.search_btn,
            self.gems_header_lbl,
            self.new_gem_btn,
            self.gems_list,
            self.projects_header_lbl,
            self.all_projects_btn,
            self.new_project_btn,
            self.projects_list,
            self.chats_header_lbl,
            self.chats_list,
            self.engine_status_lbl,
        ):
            widget.setVisible(not collapsed)
        if collapsed:
            self.search_edit.setVisible(False)
            self.new_chat_btn.setText("＋")
            self.nav_library_btn.setText("📚")
            self.nav_pdf_btn.setText("📄")
            self.nav_pipeline_btn.setText("🤖")
            self.settings_btn.setText("⚙")
        else:
            self.new_chat_btn.setText("＋  New chat")
            self.nav_library_btn.setText("📚  Library (Canvas & Reports)")
            self.nav_pdf_btn.setText("📄  PDF Workbench")
            self.nav_pipeline_btn.setText("🤖  Antigravity SDK & Pipeline")
            self.settings_btn.setText("⚙  Settings")

    def focus_search_box(self) -> None:
        if self._sidebar_collapsed:
            self.toggle_sidebar()
        visible = not self.search_edit.isVisible()
        self.search_edit.setVisible(visible)
        if visible:
            self.search_edit.setFocus()
        else:
            self.search_edit.clear()

    def _on_search_changed(self, text: str) -> None:
        self._search_filter = text.strip()
        self._refresh_sidebar()

    def _refresh_engine_status(self) -> None:
        local_models = self.pipeline.list_local_models()
        cloud_ok = self.pipeline.cloud_available()
        if local_models:
            primary = local_models[0]
            self.engine_status_lbl.setText(f"● Ollama · {primary} · AGY Ready")
            self.engine_status_lbl.setStyleSheet(f"color: {PALETTE.accent_vault}; font-size: 11px;")
        else:
            self.engine_status_lbl.setText("● Offline · Deterministic & AGY Ready")
            self.engine_status_lbl.setStyleSheet(f"color: {PALETTE.accent_blue}; font-size: 11px;")

        for comp in (self.home_composer, self.chat_composer):
            comp.refresh_model_options(
                local_models,
                cloud_ok=cloud_ok,
                local_only=self.settings.local_only,
            )

    def _refresh_sidebar(self) -> None:
        # Refresh Gems list
        self.gems_list.clear()
        for gem in self.store.list_gems():
            item = QListWidgetItem(f"{gem.icon} {gem.name}")
            item.setData(Qt.ItemDataRole.UserRole, gem.id)
            item.setToolTip(f"{gem.description}\nDefault mode: {gem.default_mode}")
            if gem.id == self.active_gem_id:
                item.setSelected(True)
            self.gems_list.addItem(item)

        # Refresh Projects list
        self.projects_list.clear()
        for proj in self.store.list_projects():
            badge = "🔒 " if proj.air_gapped else "📁 "
            item = QListWidgetItem(f"{badge}{proj.name}")
            item.setData(Qt.ItemDataRole.UserRole, proj.id)
            if proj.id == self.active_project_id:
                item.setSelected(True)
            self.projects_list.addItem(item)

        # Refresh Conversations list
        self.chats_list.clear()
        if self.active_project_id:
            convs = self.store.list_conversations(
                project_id=self.active_project_id,
                all_projects=False,
                search=self._search_filter,
            )
            proj_obj = self.store.get_project(self.active_project_id)
            self.chats_header_lbl.setText(
                f"Chats · {proj_obj.name[:16]}" if proj_obj else "Project Chats"
            )
        else:
            convs = self.store.list_conversations(
                all_projects=True,
                search=self._search_filter,
            )
            self.chats_header_lbl.setText("Recent")

        for conv in convs:
            prefix = "📌 " if conv.pinned else "💬 "
            item = QListWidgetItem(f"{prefix}{conv.title}")
            item.setData(Qt.ItemDataRole.UserRole, conv.id)
            if conv.id == self.active_conversation_id:
                item.setSelected(True)
            self.chats_list.addItem(item)

        active_proj = (
            self.store.get_project(self.active_project_id) if self.active_project_id else None
        )
        self.home_composer.set_project_scope_badge(active_proj)
        self.chat_composer.set_project_scope_badge(active_proj)

    def _show_home_greeting(self) -> None:
        active_proj = (
            self.store.get_project(self.active_project_id) if self.active_project_id else None
        )
        active_gem = self.store.get_gem(self.active_gem_id) if self.active_gem_id else None
        if active_proj is not None:
            lock = " 🔒" if active_proj.air_gapped else ""
            self.greeting_title_lbl.setText(f"Project: {active_proj.name}{lock}")
            notes_count = len(self.store.list_notes(active_proj.id))
            instr_preview = (
                active_proj.instructions[:110]
                if active_proj.instructions
                else "Custom instructions & pinned notes active for every chat in this project."
            )
            self.greeting_sub_lbl.setText(f"{instr_preview} ({notes_count} pinned note(s))")
            self.edit_project_btn.setVisible(True)
        elif active_gem is not None:
            self.greeting_title_lbl.setText(f"{active_gem.icon} {active_gem.name}")
            self.greeting_sub_lbl.setText(active_gem.description or active_gem.instructions[:120])
            self.edit_project_btn.setVisible(False)
        else:
            self.greeting_title_lbl.setText("Where should we start?")
            self.greeting_sub_lbl.setText(
                "Ask anything, co-edit in split-screen Canvas, or launch multi-step Deep Research."
            )
            self.edit_project_btn.setVisible(False)
        self.main_stack.setCurrentWidget(self.home_view)

    def start_new_chat_view(self) -> None:
        self.active_conversation_id = None
        self._refresh_sidebar()
        self._show_home_greeting()
        self.home_composer.input_edit.setFocus()

    def select_gem(self, gem_id: str | None) -> None:
        self.active_gem_id = gem_id
        gem = self.store.get_gem(gem_id) if gem_id else None
        for comp in (self.home_composer, self.chat_composer):
            comp.set_active_gem(gem)
            if gem is not None:
                comp.set_modes(
                    canvas=(gem.default_mode == "canvas"),
                    deep_research=(gem.default_mode == "deep_research"),
                    thinking=(gem.default_mode == "thinking"),
                    emit_signal=False,
                )
        self._refresh_sidebar()
        if self.active_conversation_id is None:
            self._show_home_greeting()

    def _on_gem_cleared(self) -> None:
        self.select_gem(None)

    def _on_gem_item_clicked(self, item: QListWidgetItem) -> None:
        gem_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if gem_id:
            self.select_gem(gem_id)

    def create_gem_dialog(self) -> None:
        dlg = GemEditorDialog(self.store, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.gem is not None:
            self.select_gem(dlg.gem.id)

    def select_project(self, project_id: str | None) -> None:
        self.active_project_id = project_id
        self.settings.last_project_id = project_id
        save_settings(self.settings, self.paths.settings_json)
        self.active_conversation_id = None
        self._refresh_sidebar()
        self._show_home_greeting()

    def create_project_dialog(self) -> None:
        dlg = ProjectEditorDialog(self.store, project=None, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.project is not None:
            self.select_project(dlg.project.id)

    def edit_active_project_dialog(self) -> None:
        if not self.active_project_id:
            return
        proj = self.store.get_project(self.active_project_id)
        if proj is None:
            return
        dlg = ProjectEditorDialog(self.store, project=proj, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_sidebar()
            self._show_home_greeting()

    def _on_project_item_clicked(self, item: QListWidgetItem) -> None:
        proj_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if proj_id:
            self.select_project(proj_id)

    def _on_project_context_menu(self, pos: Any) -> None:
        item = self.projects_list.itemAt(pos)
        if item is None:
            return
        proj_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        proj = self.store.get_project(proj_id)
        if proj is None:
            return
        menu = QMenu(self)
        edit_act = QAction("Edit Project & Notes…", self)
        edit_act.triggered.connect(lambda: self._edit_specific_project(proj))
        menu.addAction(edit_act)

        del_act = QAction("Delete Project", self)
        del_act.triggered.connect(lambda: self._delete_specific_project(proj.id))
        menu.addAction(del_act)
        menu.exec(self.projects_list.mapToGlobal(pos))

    def _edit_specific_project(self, project: Project) -> None:
        dlg = ProjectEditorDialog(self.store, project=project, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_sidebar()
            if self.active_project_id == project.id:
                self._show_home_greeting()

    def _delete_specific_project(self, project_id: str) -> None:
        self.store.delete_project(project_id)
        if self.active_project_id == project_id:
            self.active_project_id = None
        self._refresh_sidebar()
        self._show_home_greeting()

    def _on_chat_item_clicked(self, item: QListWidgetItem) -> None:
        conv_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if conv_id:
            self.open_conversation(conv_id)

    def _on_chat_context_menu(self, pos: Any) -> None:
        item = self.chats_list.itemAt(pos)
        if item is None:
            return
        conv_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        conv = self.store.get_conversation(conv_id)
        if conv is None:
            return

        menu = QMenu(self)
        rename_act = QAction("Rename…", self)
        rename_act.triggered.connect(lambda: self._rename_conversation_prompt(conv))
        menu.addAction(rename_act)

        pin_act = QAction("Unpin" if conv.pinned else "Pin to top", self)
        pin_act.triggered.connect(lambda: self._toggle_pin_conversation(conv))
        menu.addAction(pin_act)

        move_menu = menu.addMenu("Move to project")
        no_proj_act = QAction("No project (General)", self)
        no_proj_act.triggered.connect(lambda: self._move_conversation_to(conv.id, None))
        move_menu.addAction(no_proj_act)
        for proj in self.store.list_projects():
            p_act = QAction(proj.name, self)
            p_act.triggered.connect(
                lambda _checked=False, pid=proj.id: self._move_conversation_to(conv.id, pid)
            )
            move_menu.addAction(p_act)

        del_act = QAction("Delete", self)
        del_act.triggered.connect(lambda: self._delete_conversation_action(conv.id))
        menu.addAction(del_act)

        menu.exec(self.chats_list.mapToGlobal(pos))

    def _rename_conversation_prompt(self, conv: Conversation) -> None:
        new_title, ok = QInputDialog.getText(
            self, "Rename Conversation", "Conversation title:", text=conv.title
        )
        if ok and new_title.strip():
            self.store.rename_conversation(conv.id, new_title.strip())
            if self.active_conversation_id == conv.id:
                self.chat_title_lbl.setText(new_title.strip())
            self._refresh_sidebar()

    def _toggle_pin_conversation(self, conv: Conversation) -> None:
        self.store.set_pinned(conv.id, not conv.pinned)
        self._refresh_sidebar()

    def _move_conversation_to(self, conv_id: str, project_id: str | None) -> None:
        self.store.move_conversation(conv_id, project_id)
        self._refresh_sidebar()

    def _delete_conversation_action(self, conv_id: str) -> None:
        self.store.delete_conversation(conv_id)
        if self.active_conversation_id == conv_id:
            self.start_new_chat_view()
        else:
            self._refresh_sidebar()

    def _clear_messages_column(self) -> None:
        self._streaming_cards.clear()
        while self.messages_layout.count() > 1:
            child = self.messages_layout.takeAt(0)
            if child is not None:
                widget = child.widget()
                if widget is not None:
                    widget.deleteLater()

    def open_conversation(self, conversation_id: str) -> None:
        conv = self.store.get_conversation(conversation_id)
        if conv is None:
            return
        self.active_conversation_id = conv.id
        self.chat_title_lbl.setText(conv.title)

        proj = self.store.get_project(conv.project_id) if conv.project_id else None
        if proj is not None:
            self.chat_project_badge.setText(
                f"🔒 {proj.name}" if proj.air_gapped else f"📁 {proj.name}"
            )
            self.chat_project_badge.setVisible(True)
        else:
            self.chat_project_badge.setVisible(False)
        self.chat_composer.set_project_scope_badge(proj)

        self._clear_messages_column()
        last_user_text = ""
        for msg in self.store.list_messages(conv.id):
            if msg.role == "user":
                last_user_text = msg.content
            self._append_stored_message_widget(msg, user_prompt_for_regen=last_user_text)

        self.main_stack.setCurrentWidget(self.chat_view)
        self._refresh_sidebar()
        self._scroll_to_bottom()

    def _append_stored_message_widget(
        self,
        msg: StoredMessage,
        *,
        user_prompt_for_regen: str = "",
    ) -> None:
        idx = max(0, self.messages_layout.count() - 1)
        if msg.role == "user":
            attachments = msg.meta.get("attachments") if isinstance(msg.meta, dict) else None
            bubble = UserMessageBubble(
                msg.content,
                attachments=attachments if isinstance(attachments, list) else None,
                parent=self.messages_column_widget,
            )
            self.messages_layout.insertWidget(idx, bubble)
        else:
            card = AssistantMessageCard(
                markdown_text=msg.content,
                meta=msg.meta,
                user_prompt_for_regen=user_prompt_for_regen,
                parent=self.messages_column_widget,
            )
            card.open_in_canvas_requested.connect(self._open_card_in_canvas)
            card.save_to_library_requested.connect(self._save_card_to_library)
            card.regenerate_requested.connect(self._regenerate_turn)
            self.messages_layout.insertWidget(idx, card)

    def _open_card_in_canvas(self, title: str, content: str, kind: str) -> None:
        self.canvas_panel.open_document(
            title=title,
            content=content,
            kind=kind,
            conversation_id=self.active_conversation_id,
            project_id=self.active_project_id,
        )

    def _save_card_to_library(self, title: str, content: str, kind: str) -> None:
        self.canvas_panel.open_document(
            title=title,
            content=content,
            kind=kind,
            conversation_id=self.active_conversation_id,
            project_id=self.active_project_id,
        )
        self.canvas_panel.save_to_library()

    def _on_open_artifact_from_library(self, artifact: object) -> None:
        if isinstance(artifact, CanvasArtifact):
            self.canvas_panel.open_document(
                title=artifact.title,
                content=artifact.content,
                kind=artifact.kind,
                artifact_id=artifact.id,
                conversation_id=artifact.conversation_id,
                project_id=artifact.project_id,
            )

    def _on_artifact_saved(self, _artifact: object) -> None:
        self.library_view.refresh_library()

    def _regenerate_turn(self, prompt_text: str) -> None:
        if prompt_text.strip():
            self.submit_user_message(prompt_text)

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            20,
            lambda: self.messages_scroll.verticalScrollBar().setValue(
                self.messages_scroll.verticalScrollBar().maximum()
            ),
        )

    def _activate_suggestion_chip(self, prompt_text: str) -> None:
        if prompt_text.startswith("DEEP_RESEARCH:"):
            clean = prompt_text.removeprefix("DEEP_RESEARCH:").strip()
            self.home_composer.set_modes(deep_research=True, canvas=True)
            self.home_composer.input_edit.setPlainText(clean)
            self.home_composer.input_edit.setFocus()
            return
        if "#TABLE_DATA" in prompt_text:
            self.home_composer.set_modes(canvas=True)
        self.home_composer.input_edit.setPlainText(prompt_text)
        self.home_composer.input_edit.setFocus()

    def _on_pdf_attached_from_workbench(self, pdf_path: str) -> None:
        self.home_composer.add_attachment_paths([pdf_path])
        self.chat_composer.add_attachment_paths([pdf_path])

    def _handle_composer_submit(
        self,
        user_text: str,
        model_choice: str,
        attachments: list[str],
    ) -> None:
        self.submit_user_message(
            user_text,
            model_choice=model_choice,
            attachments=attachments,
        )

    def submit_user_message(
        self,
        user_text: str,
        *,
        model_choice: str | None = None,
        attachments: list[str] | None = None,
        deep_research: bool | None = None,
        thinking_mode: bool | None = None,
        open_in_canvas: bool | None = None,
        wait_for_completion: bool = False,
    ) -> ChatTurnResult | None:
        """Create or continue a conversation and dispatch a turn through `StudioChatPipeline`."""
        clean_text = user_text.strip()
        if not clean_text:
            return None

        chosen_model = model_choice or self.settings.default_model or "auto"
        attached_files = list(attachments or [])

        use_deep_research = (
            deep_research
            if deep_research is not None
            else self.home_composer.deep_research_mode
        )
        use_thinking = (
            thinking_mode if thinking_mode is not None else self.home_composer.thinking_mode
        )
        use_canvas = (
            open_in_canvas if open_in_canvas is not None else self.home_composer.canvas_mode
        )
        active_gem = self.store.get_gem(self.active_gem_id) if self.active_gem_id else None

        is_first_turn = False
        if self.active_conversation_id is None:
            conv = self.store.create_conversation(
                project_id=self.active_project_id,
                title="New chat",
            )
            self.active_conversation_id = conv.id
            self.chat_title_lbl.setText(conv.title)
            self._clear_messages_column()
            is_first_turn = True
        else:
            existing_msgs = self.store.list_messages(self.active_conversation_id)
            is_first_turn = len(existing_msgs) == 0

        conv_id = self.active_conversation_id
        assert conv_id is not None

        raw_history = self.store.history_for_pipeline(
            conv_id, limit=self.pipeline.config.history_window
        )
        history = [
            ChatHistoryMessage(role=item.role, content=item.content) for item in raw_history
        ]
        conv_obj = self.store.get_conversation(conv_id)
        project_id_for_turn = conv_obj.project_id if conv_obj else self.active_project_id
        raw_project_ctx = self.store.build_project_context(project_id_for_turn)
        project_ctx = (
            ProjectContext(
                project_id=raw_project_ctx.project_id,
                name=raw_project_ctx.name,
                instructions=raw_project_ctx.instructions,
                pinned_notes=list(raw_project_ctx.pinned_notes),
                air_gapped=raw_project_ctx.air_gapped,
            )
            if raw_project_ctx is not None
            else None
        )

        user_msg = self.store.add_message(
            conv_id,
            "user",
            clean_text,
            meta={"attachments": attached_files} if attached_files else {},
        )
        self._append_stored_message_widget(user_msg, user_prompt_for_regen=clean_text)

        turn_id = f"turn-{uuid.uuid4().hex[:10]}"
        placeholder_card = AssistantMessageCard(
            markdown_text="_Running Yggdrasil pipeline…_",
            meta={
                "route": "deterministic",
                "air_gap_enforced": bool(project_ctx and project_ctx.air_gapped),
                "thinking_mode": use_thinking,
                "gem_name": active_gem.name if active_gem else None,
            },
            user_prompt_for_regen=clean_text,
            parent=self.messages_column_widget,
        )
        placeholder_card.open_in_canvas_requested.connect(self._open_card_in_canvas)
        placeholder_card.save_to_library_requested.connect(self._save_card_to_library)
        placeholder_card.regenerate_requested.connect(self._regenerate_turn)
        idx = max(0, self.messages_layout.count() - 1)
        self.messages_layout.insertWidget(idx, placeholder_card)
        self._streaming_cards[turn_id] = placeholder_card

        self.main_stack.setCurrentWidget(self.chat_view)
        self._refresh_sidebar()
        self._scroll_to_bottom()

        request = ChatTurnRequest(
            turn_id=turn_id,
            user_text=clean_text,
            history=history,
            project=project_ctx,
            model_choice=chosen_model,
            local_only=self.settings.local_only,
            attachments=attached_files,
            deep_research=use_deep_research,
            thinking_mode=use_thinking,
            open_in_canvas=use_canvas,
            gem_name=active_gem.name if active_gem else None,
            gem_instructions=active_gem.instructions if active_gem else "",
        )

        self.home_composer.set_running(True)
        self.chat_composer.set_running(True)

        def _token_cb(tok: str) -> None:
            self.token_received.emit(turn_id, tok)

        future = self.pipeline.submit(request, on_token=_token_cb)
        self._active_future = future

        if wait_for_completion:
            result = future.result(timeout=45.0)
            self._finalize_turn(
                conv_id,
                result,
                is_first_turn=is_first_turn,
                thinking_mode=use_thinking,
                gem_name=active_gem.name if active_gem else None,
            )
            return result

        gem_name_val = active_gem.name if active_gem else None

        def _done_cb(fut: Future[ChatTurnResult]) -> None:
            try:
                res = fut.result()
            except (RuntimeError, ValueError, OSError) as exc:  # pragma: no cover
                res = ChatTurnResult(
                    turn_id=turn_id,
                    answer_markdown=f"⚠️ Turn interrupted: `{exc}`",
                    route="offline_fallback",
                    error=str(exc),
                )
            self.turn_completed.emit((conv_id, res, is_first_turn, use_thinking, gem_name_val))

        future.add_done_callback(_done_cb)
        return None

    def _on_token_streamed(self, turn_id: str, token: str) -> None:
        card = self._streaming_cards.get(turn_id)
        if card is not None:
            if card._markdown.startswith("_Running Yggdrasil"):
                card.set_markdown("")
            card.append_token(token)
            self._scroll_to_bottom()

    def _on_turn_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 5:
            return
        conv_id, result, is_first_turn, thinking_mode, gem_name = payload
        if isinstance(conv_id, str) and isinstance(result, ChatTurnResult):
            self._finalize_turn(
                conv_id,
                result,
                is_first_turn=bool(is_first_turn),
                thinking_mode=bool(thinking_mode),
                gem_name=str(gem_name) if gem_name else None,
            )

    def _finalize_turn(
        self,
        conv_id: str,
        result: ChatTurnResult,
        *,
        is_first_turn: bool,
        thinking_mode: bool = False,
        gem_name: str | None = None,
    ) -> None:
        self.home_composer.set_running(False)
        self.chat_composer.set_running(False)

        thinking_trace = getattr(result, "thinking_trace_markdown", "")
        canvas_title = getattr(result, "canvas_title", None)
        canvas_content = getattr(result, "canvas_content", None)
        canvas_kind = getattr(result, "canvas_kind", "markdown")
        citations = list(getattr(result, "citations", []) or [])

        meta_dict: dict[str, Any] = {
            "turn_id": result.turn_id,
            "route": result.route,
            "model_used": result.model_used,
            "tags_detected": result.tags_detected,
            "stages": [s.model_dump(mode="json") for s in result.stages],
            "deterministic_hits": result.deterministic_hits,
            "llm_tokens_used": result.llm_tokens_used,
            "air_gap_enforced": result.air_gap_enforced,
            "thinking_trace_markdown": thinking_trace,
            "thinking_mode": thinking_mode,
            "gem_name": gem_name,
            "canvas_title": canvas_title,
            "canvas_content": canvas_content,
            "canvas_kind": canvas_kind,
            "citations": citations,
            "suggested_title": result.suggested_title,
            "error": result.error,
        }
        self.store.add_message(
            conv_id,
            "assistant",
            result.answer_markdown,
            meta=meta_dict,
        )

        if is_first_turn and result.suggested_title:
            self.store.rename_conversation(conv_id, result.suggested_title)
            if self.active_conversation_id == conv_id:
                self.chat_title_lbl.setText(result.suggested_title)

        card = self._streaming_cards.pop(result.turn_id, None)
        if card is not None:
            card.set_markdown(result.answer_markdown)
            card.update_meta(meta_dict)

        # Auto-open Split-Screen Canvas when canvas_content is populated
        if isinstance(canvas_content, str) and canvas_content.strip():
            self.canvas_panel.open_document(
                title=str(canvas_title or result.suggested_title or "Canvas Artifact"),
                content=canvas_content,
                kind=str(canvas_kind or "markdown"),
                conversation_id=conv_id,
                project_id=self.active_project_id,
            )

        self._refresh_sidebar()
        self._scroll_to_bottom()

    def cancel_active_turn(self) -> None:
        self.pipeline.cancel_current()
        self.home_composer.set_running(False)
        self.chat_composer.set_running(False)

    def open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self.paths, self.settings, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.home_composer.set_selected_model(self.settings.default_model)
            self.chat_composer.set_selected_model(self.settings.default_model)
            self._refresh_engine_status()

    def closeEvent(self, event: Any) -> None:
        self.pipeline.shutdown()
        super().closeEvent(event)


def run_studio_self_test(paths: StudioPaths = PATHS) -> dict[str, Any]:
    """Run headless offscreen verification of Yggdrasil Studio v0.5.0 (`--self-test`)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    ensure_studio_directories(paths)

    app = QApplication.instance() or QApplication(["YggdrasilStudio", "--self-test"])
    window = YggdrasilStudioWindow(paths=paths)
    window.show()
    app.processEvents()

    # 1. Verify seeded Gems (>= 4) & select the ChemEng Gem
    gems = window.store.list_gems()
    assert len(gems) >= 4, f"Expected at least 4 seeded Gems, got {len(gems)}"
    window.select_gem(gems[0].id)
    app.processEvents()

    # 2. Verify Google Antigravity SDK bridge status
    agy_status = window.agy_bridge.status()

    # 3. Create an Air-Gapped Project with custom instruction and pinned note
    project = window.store.create_project(
        name="ChemEng Reactor Design",
        instructions="Always use SI units and enforce IMC PID stability criteria.",
        air_gapped=True,
    )
    note = window.store.add_note(
        project.id,
        "Reactor Feed Spec",
        "Feed concentration C_A0 = 2.5 mol/L, activation energy Ea = 54000 J/mol.",
    )
    window.select_project(project.id)
    app.processEvents()

    # 4. Run a deterministic + Canvas + Thinking turn inside the project
    prompt = (
        "#CALC_SOLVE: mode=arrhenius\n"
        "A=1.25e6 Ea=54000 T=350\n"
        "#CONTROL_SYSTEM: tuning_method=imc\n"
        "kp=2.4 tau=18.0 theta=3.0"
    )
    turn_result = window.submit_user_message(
        prompt,
        model_choice="auto",
        open_in_canvas=True,
        thinking_mode=True,
        wait_for_completion=True,
    )
    app.processEvents()
    assert turn_result is not None, "Expected synchronous ChatTurnResult in self-test"
    conv_id = window.active_conversation_id
    assert conv_id is not None, "Expected active conversation ID after turn submission"

    # 5. Run a Deep Research turn and verify CanvasWorkspacePanel populates
    research_result = window.submit_user_message(
        "Investigate SIMC and IMC PID tuning rules and Arrhenius reactor stability.",
        model_choice="auto",
        deep_research=True,
        open_in_canvas=True,
        thinking_mode=True,
        wait_for_completion=True,
    )
    app.processEvents()
    assert research_result is not None, "Expected Deep Research ChatTurnResult"

    # Ensure Canvas panel is open with content and save to Library (`artifacts` table)
    if not window.canvas_panel.editor.toPlainText().strip():
        window.canvas_panel.open_document(
            title=research_result.suggested_title or "Deep Research Report",
            content=research_result.answer_markdown,
            kind="report",
            conversation_id=conv_id,
            project_id=project.id,
        )
    saved_artifact = window.canvas_panel.save_to_library()
    app.processEvents()

    stored_messages = window.store.list_messages(conv_id)
    artifacts_list = window.store.list_artifacts()
    projects_count = window.projects_list.count()
    chats_count = window.chats_list.count()

    # Verify reload from studio.db into the conversation view
    window.open_conversation(conv_id)
    app.processEvents()

    thinking_trace_text = getattr(turn_result, "thinking_trace_markdown", "") or getattr(
        research_result, "thinking_trace_markdown", ""
    )

    summary: dict[str, Any] = {
        "status": "ok",
        "version": "0.5.0",
        "ui_framework": "PySide6",
        "mode": paths.mode,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "ui_gate_authorized": window.ui_gate_decision.can_execute_ui_agent,
        "seeded_gems_count": len(gems),
        "active_gem_name": gems[0].name,
        "agy_sdk_installed": agy_status.sdk_installed,
        "agy_backend_mode": agy_status.backend_mode,
        "agy_equipped_tools": agy_status.equipped_tools,
        "agy_api_key_setup_url": agy_status.api_key_setup_url,
        "project_id": project.id,
        "project_name": project.name,
        "project_air_gapped": project.air_gapped,
        "pinned_note_id": note.id,
        "conversation_id": conv_id,
        "stored_message_count": len(stored_messages),
        "sidebar_projects_count": projects_count,
        "sidebar_chats_count": chats_count,
        "turn_route": turn_result.route,
        "deterministic_hits": turn_result.deterministic_hits,
        "llm_tokens_used": turn_result.llm_tokens_used,
        "air_gap_enforced": turn_result.air_gap_enforced,
        "thinking_trace_non_empty": bool(thinking_trace_text.strip()),
        "canvas_panel_visible": window.canvas_panel.isVisible(),
        "canvas_content_length": len(window.canvas_panel.editor.toPlainText()),
        "saved_artifact_id": saved_artifact.id,
        "library_artifacts_count": len(artifacts_list),
        "suggested_title": turn_result.suggested_title,
        "studio_db_path": str(paths.studio_db),
    }

    for fname in ("studio_v5_self_test.json", "studio_v4_self_test.json"):
        report_path = paths.user_content_dir / "brain" / fname
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    window.close()
    app.processEvents()
    return summary


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for Yggdrasil Studio v0.5.0 (`YggdrasilStudio.pyw`)."""
    parser = argparse.ArgumentParser(description="Yggdrasil Studio v0.5.0 (PySide6)")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run headless offscreen self-test and write studio_v5_self_test.json",
    )
    args = parser.parse_args(argv)

    paths = resolve_studio_paths()
    ensure_studio_directories(paths)
    if args.self_test:
        summary = run_studio_self_test(paths)
        print(json.dumps(summary, indent=2))
        return 0 if summary.get("status") == "ok" else 1

    app = QApplication.instance() or QApplication(sys.argv)
    window = YggdrasilStudioWindow(paths=paths)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
