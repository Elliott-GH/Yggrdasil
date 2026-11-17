"""Conditional nested UI/UX agent (`[/userinterface]`) for Yggdrasil Studio (SPEC-002)."""

from __future__ import annotations

import html
import re
from typing import Literal

from pydantic import BaseModel, Field

VISUAL_GUI_KEYWORDS: frozenset[str] = frozenset(
    {
        "gui",
        "visual",
        "interface",
        "appearance",
        "animation",
        "theme",
        "window",
        "layout",
        "styling",
        "qol",
        "frontend",
        "button",
        "dark mode",
    }
)

_EXPLICIT_UI_COMMAND_RE = re.compile(r"(?:\[/userinterface\]|/userinterface\b)", re.IGNORECASE)
_KEYWORD_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(kw) for kw in sorted(VISUAL_GUI_KEYWORDS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


class UiHandoffDecision(BaseModel):
    """Conditional activation gate output for the independent [/userinterface] nested agent."""

    explicit_command_detected: bool
    visual_keywords_detected: list[str] = Field(default_factory=list)
    can_execute_ui_agent: bool
    requires_handoff_confirmation: bool
    handoff_prompt: str = ""


class UiThemeSpec(BaseModel):
    """Gemini-inspired Nordic Aurora branding and QoL ergonomics configuration."""

    brand_name: str = "Yggdrasil Studio"
    tagline: str = "Hybrid Local-to-Cloud Sovereign AI"
    accent_primary: str = "#38bdf8"
    accent_secondary: str = "#8b5cf6"
    accent_vault: str = "#10b981"
    background_canvas: str = "#070b14"
    surface_panel: str = "#111827"
    animation_duration_s: float = Field(default=3.5, gt=0.0)
    compact_mode: bool = False
    ui_mode: Literal["native_desktop", "web_studio"] = "native_desktop"


def build_native_tk_style_tokens(theme: UiThemeSpec | None = None) -> dict[str, str]:
    """Return tkinter/ttk Nordic Aurora theme palette and font specs for Version 3 desktop GUI."""
    active = theme or UiThemeSpec()
    return {
        "bg_canvas": active.background_canvas,
        "bg_surface": active.surface_panel,
        "bg_surface_alt": "#172033",
        "border": "#26334d",
        "text_primary": "#e2e8f0",
        "text_muted": "#94a3b8",
        "accent_primary": active.accent_primary,
        "accent_secondary": active.accent_secondary,
        "accent_vault": active.accent_vault,
        "accent_warning": "#f59e0b",
        "font_ui": "Segoe UI",
        "font_title": "Segoe UI Semibold",
        "font_mono": "Consolas",
    }


class UiAgentInput(BaseModel):
    """Typed request payload for UserInterfaceNestedAgent."""

    request_id: str = Field(min_length=1)
    raw_instruction: str = Field(min_length=1)
    user_confirmed_handoff: bool = False
    theme_overrides: dict[str, str] = Field(default_factory=dict)


class UiAgentOutput(BaseModel):
    """Structured deterministic output from UserInterfaceNestedAgent."""

    request_id: str
    status: Literal["executed", "handoff_confirmation_required", "no_ui_action"]
    handoff_decision: UiHandoffDecision
    theme: UiThemeSpec = Field(default_factory=UiThemeSpec)
    generated_html_preview: str = ""
    qol_features_enabled: list[str] = Field(default_factory=list)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


def check_ui_handoff_gate(
    raw_instruction: str,
    user_confirmed_handoff: bool = False,
) -> UiHandoffDecision:
    """Enforce Law 7: activate [/userinterface] only on explicit command or confirmed handoff."""
    explicit = bool(_EXPLICIT_UI_COMMAND_RE.search(raw_instruction))
    seen: list[str] = []
    for match in _KEYWORD_PATTERN.finditer(raw_instruction):
        kw = match.group(0).lower()
        if kw not in seen:
            seen.append(kw)

    if explicit or user_confirmed_handoff:
        return UiHandoffDecision(
            explicit_command_detected=explicit,
            visual_keywords_detected=seen,
            can_execute_ui_agent=True,
            requires_handoff_confirmation=False,
            handoff_prompt="",
        )

    if seen:
        joined = ", ".join(seen)
        return UiHandoffDecision(
            explicit_command_detected=False,
            visual_keywords_detected=seen,
            can_execute_ui_agent=False,
            requires_handoff_confirmation=True,
            handoff_prompt=(
                f"Visual/GUI keywords detected ({joined}) without [/userinterface]. "
                "Would you like the Master Agent to hand this over to the [/userinterface] agent?"
            ),
        )

    return UiHandoffDecision(
        explicit_command_detected=False,
        visual_keywords_detected=[],
        can_execute_ui_agent=False,
        requires_handoff_confirmation=False,
        handoff_prompt="",
    )


class UserInterfaceNestedAgent:
    """Independent conditional nested agent managing Yggdrasil Studio UI, animations & QoL."""

    DEFAULT_QOL_FEATURES: tuple[str, ...] = (
        "gemini_aurora_dark_theme",
        "tag_quick_insert_chips",
        "ctrl_enter_run_shortcut",
        "live_wi_tree_animation",
        "air_gap_privacy_shield_badge",
        "changelog_version_drawer",
        "user_content_explorer",
    )

    def evaluate_or_execute(self, payload: UiAgentInput) -> UiAgentOutput:
        """Check conditional activation rules and build UI theme/preview only when authorized."""
        decision = check_ui_handoff_gate(
            payload.raw_instruction,
            user_confirmed_handoff=payload.user_confirmed_handoff,
        )
        theme = UiThemeSpec()

        if decision.requires_handoff_confirmation:
            return UiAgentOutput(
                request_id=payload.request_id,
                status="handoff_confirmation_required",
                handoff_decision=decision,
                theme=theme,
            )

        if not decision.can_execute_ui_agent:
            return UiAgentOutput(
                request_id=payload.request_id,
                status="no_ui_action",
                handoff_decision=decision,
                theme=theme,
            )

        lower = payload.raw_instruction.lower()
        updates: dict[str, object] = {}
        allowed_str_fields = {
            "brand_name",
            "tagline",
            "accent_primary",
            "accent_secondary",
            "accent_vault",
            "background_canvas",
            "surface_panel",
        }
        for key, value in payload.theme_overrides.items():
            if key in allowed_str_fields:
                updates[key] = value
        if "compact" in lower:
            updates["compact_mode"] = True
        if "fast" in lower and "animation" in lower:
            updates["animation_duration_s"] = 1.8
        if updates:
            theme = theme.model_copy(update=updates)

        preview_html = (
            f'<div class="ygg-studio-banner" style="background:{html.escape(theme.surface_panel)};'
            f'border:1px solid {html.escape(theme.accent_primary)};border-radius:16px;padding:16px">'
            f'<strong style="color:{html.escape(theme.accent_primary)}">'
            f"{html.escape(theme.brand_name)}</strong> — "
            f"<span>{html.escape(theme.tagline)}</span>"
            "</div>"
        )
        return UiAgentOutput(
            request_id=payload.request_id,
            status="executed",
            handoff_decision=decision,
            theme=theme,
            generated_html_preview=preview_html,
            qol_features_enabled=list(self.DEFAULT_QOL_FEATURES),
        )
