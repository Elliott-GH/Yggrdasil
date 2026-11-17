# Embedded & Nested Agents Changelog — Version 0.5.0

- **Version:** `0.5.0`
- **Date:** `2026-11-17`
- **Scope:** Google Antigravity SDK Bridge (`agy_bridge.py`), Multi-Step Deep Research Engine (`DeepResearchReport`), Thinking Trace & Canvas Artifact Generation (`chat_pipeline.py`)

## Changed / Added
1. **Google Antigravity SDK Bridge (`/03-agent-foundry/yggdrasil_agents/agy_bridge.py`):**
   - Installed `google-antigravity==0.1.23` and implemented `AgySdkBridge`, `AgyBridgeConfig`, `AgyBridgeStatus`, `DeepResearchSection`, and `DeepResearchReport`.
   - Constructs verified `google.antigravity` configurations (`LocalOpenAIAgentConfig(...).lightweight()` for local Ollama/LM Studio with zero API key, `LiteRTAgentConfig` for on-device LiteRT-LM, and `LocalAgentConfig` for hosted Gemini with `BudgetConfig`, `CompactionConfig`, and `https://aistudio.google.com/app/api-keys` setup guidance).
   - Equips custom deterministic Yggdrasil tool wrappers (`solve_calculation`, `analyse_table`, `tune_pid_controller`, `optimise_python_code`, `verify_research_gaps`).
   - Implements `run_deep_research()` generating a multi-step investigation plan, executing deterministic calculations and local verified reference matching (`evaluate_local_research_gaps`), enforcing strict air-gap isolation (`air_gapped=True` blocks hosted Gemini), and returning a Canvas-ready `markdown_document`.
2. **Version 5 Conversational Pipeline Extensions (`/03-agent-foundry/yggdrasil_agents/chat_pipeline.py`):**
   - Extended `ChatTurnRequest` (`deep_research`, `thinking_mode`, `open_in_canvas`, `gem_name`, `gem_instructions`) and `ChatTurnResult` (`thinking_trace_markdown`, `canvas_title`, `canvas_content`, `canvas_kind`, `citations`).
   - Generates structured `thinking_trace_markdown` on every turn and automatically populates `canvas_content` when `open_in_canvas=True`, `deep_research=True`, or when code/table/report slices execute.
