"""Gemini Dark Studio palette, tokens, and Qt Style Sheet (QSS) for Yggdrasil Studio v0.5.0.

Governs the visual identity of Yggdrasil Studio under `[/userinterface]` (`SPEC-004` & `SPEC-005`):
- Main canvas background `#0b0c10` with radial blue glow (`#132247` -> `#0d152c` -> `#0b0c10`)
- Collapsible left sidebar (`#131418`, border `#1f2229`, ~264px expanded / ~56px collapsed rail)
- Split-screen interactive **Gemini Canvas Panel** (`#11131a` surface, dual tabs for `✏️ Co-Editor`
  and `👁️ Live Preview`, action chip toolbar)
- Pill composer (`#1b1d24`, border `#2b2f3a`, radius 26px) + glowing active Mode & Gem pills
- Collapsible **Thinking & Routing Trace Drawer** (`#151822` card above assistant replies)
- Per-message Gemini action bar & Gems / Artifact Library cards
- Air-gapped vault badge (`#10b981`)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StudioPalette:
    """Color and dimension tokens for the Gemini-inspired Yggdrasil Studio v0.5.0 interface."""

    bg_canvas: str = "#0b0c10"
    bg_glow_inner: str = "#132247"
    bg_glow_mid: str = "#0d152c"
    bg_sidebar: str = "#131418"
    bg_surface: str = "#171920"
    bg_canvas_panel: str = "#11131a"
    bg_thinking_drawer: str = "#151822"
    bg_composer: str = "#1b1d24"
    bg_bubble_user: str = "#1f2430"
    bg_bubble_assistant: str = "#13161f"
    bg_chip: str = "#161922"
    bg_chip_hover: str = "#222736"
    border_subtle: str = "#1f2229"
    border_composer: str = "#2b2f3a"
    border_focus: str = "#4f8cff"
    text_primary: str = "#e8eaed"
    text_secondary: str = "#9aa0a6"
    text_muted: str = "#6e7681"
    accent_blue: str = "#8ab4f8"
    accent_purple: str = "#c58af9"
    accent_vault: str = "#10b981"
    accent_warning: str = "#f59e0b"
    accent_danger: str = "#ef4444"
    sidebar_expanded_width: int = 268
    sidebar_collapsed_width: int = 56
    chat_column_max_width: int = 780


PALETTE = StudioPalette()


def build_studio_stylesheet(p: StudioPalette = PALETTE) -> str:
    """Build the master Qt Style Sheet (QSS) for Yggdrasil Studio v0.5.0."""
    return f"""
    QMainWindow, QDialog {{
        background-color: {p.bg_canvas};
        color: {p.text_primary};
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 13px;
    }}

    QWidget {{
        color: {p.text_primary};
        font-family: "Segoe UI", "Inter", sans-serif;
    }}

    /* Left Collapsible Sidebar */
    QFrame#SidebarFrame {{
        background-color: {p.bg_sidebar};
        border-right: 1px solid {p.border_subtle};
    }}

    QLabel#BrandTitle {{
        color: {p.text_primary};
        font-size: 16px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }}

    QLabel#SectionHeader {{
        color: {p.text_secondary};
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        padding: 5px 8px 2px 8px;
    }}

    QPushButton#NewChatPillButton {{
        background-color: #1e222d;
        color: {p.text_primary};
        border: 1px solid {p.border_composer};
        border-radius: 18px;
        padding: 8px 14px;
        font-size: 13px;
        font-weight: 600;
        text-align: left;
    }}
    QPushButton#NewChatPillButton:hover {{
        background-color: #262b38;
        border-color: {p.accent_blue};
    }}

    QPushButton#SidebarNavButton {{
        background-color: transparent;
        color: {p.text_secondary};
        border: none;
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 13px;
        text-align: left;
    }}
    QPushButton#SidebarNavButton:hover {{
        background-color: #1c1f28;
        color: {p.text_primary};
    }}
    QPushButton#SidebarNavButton[active="true"] {{
        background-color: #1f2637;
        color: {p.accent_blue};
        font-weight: 600;
    }}

    QPushButton#IconButton {{
        background-color: transparent;
        color: {p.text_secondary};
        border: none;
        border-radius: 14px;
        padding: 5px;
        font-size: 14px;
    }}
    QPushButton#IconButton:hover {{
        background-color: #20242f;
        color: {p.text_primary};
    }}

    /* Sidebar Lists (Gems, Projects & Conversations) */
    QListWidget#SidebarList {{
        background-color: transparent;
        border: none;
        outline: none;
        padding: 2px;
    }}
    QListWidget#SidebarList::item {{
        background-color: transparent;
        color: {p.text_secondary};
        border-radius: 9px;
        padding: 6px 10px;
        margin: 1px 0px;
    }}
    QListWidget#SidebarList::item:hover {{
        background-color: #1b1e27;
        color: {p.text_primary};
    }}
    QListWidget#SidebarList::item:selected {{
        background-color: #1e2638;
        color: {p.accent_blue};
        font-weight: 600;
    }}

    /* Greeting Typography */
    QLabel#GreetingHeroLabel {{
        color: {p.text_primary};
        font-size: 32px;
        font-weight: 600;
        letter-spacing: -0.4px;
        background: transparent;
    }}
    QLabel#GreetingSubLabel {{
        color: {p.text_secondary};
        font-size: 14px;
        background: transparent;
    }}

    /* Pill Composer Bar & Active Mode Pills */
    QFrame#ComposerPillFrame {{
        background-color: {p.bg_composer};
        border: 1px solid {p.border_composer};
        border-radius: 26px;
    }}
    QFrame#ComposerPillFrame[focused="true"] {{
        border: 1px solid {p.border_focus};
    }}

    QPlainTextEdit#ComposerInput {{
        background-color: transparent;
        color: {p.text_primary};
        border: none;
        font-size: 14px;
        selection-background-color: #2b4c7e;
    }}

    QPushButton#ComposerModePill {{
        background-color: #1d273b;
        color: {p.accent_blue};
        border: 1px solid #35507d;
        border-radius: 12px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#ComposerModePill:hover {{
        background-color: #26344f;
        border-color: {p.accent_blue};
    }}

    QPushButton#ComposerGemPill {{
        background-color: #251b38;
        color: {p.accent_purple};
        border: 1px solid #593b87;
        border-radius: 12px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#ComposerGemPill:hover {{
        background-color: #31234a;
        border-color: {p.accent_purple};
    }}

    QComboBox#ModelSelectorCombo {{
        background-color: #232733;
        color: {p.text_secondary};
        border: 1px solid {p.border_composer};
        border-radius: 14px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 600;
    }}
    QComboBox#ModelSelectorCombo:hover {{
        color: {p.text_primary};
        border-color: {p.accent_blue};
    }}
    QComboBox#ModelSelectorCombo::drop-down {{
        border: none;
        width: 18px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.bg_surface};
        color: {p.text_primary};
        border: 1px solid {p.border_composer};
        selection-background-color: #23304d;
        padding: 4px;
    }}

    QPushButton#SendPillButton {{
        background-color: {p.accent_blue};
        color: #081020;
        border: none;
        border-radius: 17px;
        font-size: 13px;
        font-weight: 700;
        min-width: 34px;
        max-width: 34px;
        min-height: 34px;
        max-height: 34px;
    }}
    QPushButton#SendPillButton:hover {{
        background-color: #a3c4fa;
    }}
    QPushButton#SendPillButton[running="true"] {{
        background-color: {p.accent_danger};
        color: #ffffff;
    }}

    /* Suggestion Chips */
    QPushButton#SuggestionChip {{
        background-color: {p.bg_chip};
        color: {p.text_secondary};
        border: 1px solid {p.border_subtle};
        border-radius: 18px;
        padding: 9px 16px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton#SuggestionChip:hover {{
        background-color: {p.bg_chip_hover};
        color: {p.text_primary};
        border-color: {p.border_composer};
    }}

    /* Conversation Message Cards */
    QFrame#UserBubbleFrame {{
        background-color: {p.bg_bubble_user};
        border: 1px solid #2b3242;
        border-radius: 18px;
    }}
    QFrame#AssistantCardFrame {{
        background-color: transparent;
        border: none;
    }}
    QTextBrowser#AssistantMarkdownBrowser {{
        background-color: transparent;
        color: {p.text_primary};
        border: none;
        font-size: 14px;
        line-height: 1.5;
    }}

    /* Collapsible Thinking & Routing Trace Drawer */
    QPushButton#ThinkingToggleButton {{
        background-color: {p.bg_thinking_drawer};
        color: {p.accent_purple};
        border: 1px solid #2b2640;
        border-radius: 12px;
        padding: 4px 12px;
        font-size: 11px;
        font-weight: 600;
        text-align: left;
    }}
    QPushButton#ThinkingToggleButton:hover {{
        border-color: {p.accent_purple};
        background-color: #1c2030;
    }}
    QFrame#ThinkingDrawerFrame {{
        background-color: {p.bg_thinking_drawer};
        border: 1px solid #282c3e;
        border-radius: 12px;
    }}

    /* Per-Message Gemini Action Bar & Route Badges */
    QPushButton#MessageActionButton {{
        background-color: #151821;
        color: {p.text_secondary};
        border: 1px solid {p.border_subtle};
        border-radius: 10px;
        padding: 3px 9px;
        font-size: 11px;
    }}
    QPushButton#MessageActionButton:hover {{
        background-color: #1e2433;
        color: {p.text_primary};
        border-color: {p.accent_blue};
    }}

    QPushButton#RouteBadgeButton {{
        background-color: #141822;
        color: {p.text_secondary};
        border: 1px solid {p.border_subtle};
        border-radius: 11px;
        padding: 3px 10px;
        font-size: 11px;
        text-align: left;
    }}
    QPushButton#RouteBadgeButton:hover {{
        border-color: {p.accent_blue};
        color: {p.text_primary};
    }}

    QLabel#AirGapBadge {{
        background-color: #0b2920;
        color: {p.accent_vault};
        border: 1px solid {p.accent_vault};
        border-radius: 10px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 600;
    }}

    /* Split-Screen Gemini Canvas Panel */
    QFrame#CanvasWorkspaceFrame {{
        background-color: {p.bg_canvas_panel};
        border-left: 1px solid {p.border_composer};
    }}
    QPlainTextEdit#CanvasCodeEditor {{
        background-color: #0e1017;
        color: {p.text_primary};
        border: 1px solid {p.border_subtle};
        border-radius: 10px;
        padding: 10px;
        font-family: "Consolas", "Cascadia Code", monospace;
        font-size: 13px;
    }}
    QTextBrowser#CanvasPreviewBrowser {{
        background-color: #12151f;
        color: {p.text_primary};
        border: 1px solid {p.border_subtle};
        border-radius: 10px;
        padding: 12px;
        font-size: 13px;
    }}
    QPushButton#CanvasActionChip {{
        background-color: #1a1f2c;
        color: {p.text_primary};
        border: 1px solid {p.border_composer};
        border-radius: 11px;
        padding: 5px 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#CanvasActionChip:hover {{
        background-color: #242c40;
        border-color: {p.accent_blue};
    }}

    /* Tab Widget (Canvas Co-Editor / Live Preview & Pipeline / AGY Hub) */
    QTabWidget::pane {{
        border: 1px solid {p.border_subtle};
        border-radius: 10px;
        background-color: {p.bg_surface};
    }}
    QTabBar::tab {{
        background-color: #151821;
        color: {p.text_secondary};
        border: 1px solid {p.border_subtle};
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 6px 14px;
        margin-right: 4px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: #1f2637;
        color: {p.accent_blue};
        border-color: {p.border_composer};
    }}

    /* Menus */
    QMenu {{
        background-color: {p.bg_surface};
        color: {p.text_primary};
        border: 1px solid {p.border_composer};
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 6px 20px 6px 12px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background-color: #222b3d;
        color: {p.accent_blue};
    }}

    /* Panels, Inputs, Cards */
    QFrame#SurfaceCard {{
        background-color: {p.bg_surface};
        border: 1px solid {p.border_subtle};
        border-radius: 14px;
    }}
    QLineEdit, QPlainTextEdit, QTextEdit {{
        background-color: #141720;
        color: {p.text_primary};
        border: 1px solid {p.border_composer};
        border-radius: 8px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {p.border_focus};
    }}
    QPushButton#PrimaryButton {{
        background-color: {p.accent_blue};
        color: #091224;
        border: none;
        border-radius: 8px;
        padding: 7px 14px;
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: #a3c4fa;
    }}
    QPushButton#SecondaryButton {{
        background-color: #1f232e;
        color: {p.text_primary};
        border: 1px solid {p.border_composer};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton#SecondaryButton:hover {{
        border-color: {p.accent_blue};
    }}
    QSplitter::handle {{
        background-color: {p.border_subtle};
        width: 2px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #282d3a;
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #3a4154;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    """
