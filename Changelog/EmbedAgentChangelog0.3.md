# Embed & Nested Agents Changelog — Version 0.3.0

- **Version:** `0.3.0`
- **Date:** `2026-11-17`
- **Scope:** `ui_agent.py` Native Desktop Theme Tokens (`build_native_tk_style_tokens`) & Standalone `Version 3` Packaging

## Changed / Added
1. **`ui_agent.py` Native Desktop Support (`03-agent-foundry`):**
   - Extended `UiThemeSpec` with `ui_mode: Literal["native_desktop", "web_studio"] = "native_desktop"`.
   - Added `build_native_tk_style_tokens(theme: UiThemeSpec | None = None) -> dict[str, str]` returning Nordic Aurora colors and `Segoe UI` / `Consolas` font specs consumed directly by `native_gui.py` and exported to `Version 3/resources/tk_theme_tokens.json`.
   - Exported `build_native_tk_style_tokens` in `yggdrasil_agents.__init__` and `yggdrasil_agents.nano_models`.
2. **Unit Tests (`/03-agent-foundry/tests/test_nested_nano_and_tools.py`):**
   - Added `test_native_desktop_tokens_and_smart_pdf_workbench` validating `build_native_tk_style_tokens` keys/colors and `UiThemeSpec.ui_mode == "native_desktop"`.
