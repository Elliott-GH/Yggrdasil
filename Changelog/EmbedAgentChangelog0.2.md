# Embed & Nested Agents Changelog — Version 0.2.0

- **Version:** `0.2.0`
- **Date:** `2026-11-17`
- **Scope:** Independent Conditional `UserInterfaceNestedAgent` (`ui_agent.py`) & Standalone Weight/Manifest Exports

## Changed / Added
1. **New Conditional UI Nested Agent (`/03-agent-foundry/yggdrasil_agents/ui_agent.py`):**
   - Implemented `VISUAL_GUI_KEYWORDS` detector (`gui`, `visual`, `interface`, `appearance`, `animation`, `theme`, `window`, `layout`, `styling`, `qol`, `frontend`, `button`, `dark mode`) and regex gate `check_ui_handoff_gate(...)`.
   - Implemented `UserInterfaceNestedAgent.evaluate_or_execute(UiAgentInput) -> UiAgentOutput`:
     - Returns `status="handoff_confirmation_required"` (`can_execute_ui_agent=False`) if visual/GUI keywords appear without `[/userinterface]` and without `user_confirmed_handoff=True`.
     - Executes deterministically (`0` LLM tokens, `0` VRAM) returning `UiThemeSpec`, `generated_html_preview`, and `qol_features_enabled` when `[/userinterface]` or confirmed handoff is present.
2. **Package & Weight Exports:**
   - Re-exported `UserInterfaceNestedAgent`, `check_ui_handoff_gate`, `UiAgentInput`, `UiAgentOutput`, `UiHandoffDecision`, `UiThemeSpec`, and `VISUAL_GUI_KEYWORDS` from `yggdrasil_agents.__init__` and `yggdrasil_agents.nano_models`.
   - Exported `micro_model_1024_weights.json` and `nano_agents_manifest.json` into standalone `agents_and_lms/` and `user_content/exports/` during sync.
3. **Unit Tests (`/03-agent-foundry/tests/test_nested_nano_and_tools.py`):**
   - Added `test_conditional_userinterface_agent_gate` covering non-UI pass-through, visual-keyword handoff hold, explicit `[/userinterface]` execution, and confirmed handoff theme overrides.
