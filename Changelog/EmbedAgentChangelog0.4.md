# Embedded & Nested Agents Changelog — Version 0.4.0

- **Version:** `0.4.0`
- **Date:** `2026-11-17`
- **Scope:** Conversational Nested Pipeline (`chat_pipeline.py`), Local & Cloud Streaming (`local_engine.py`, `leaves.py`), and Readable Tool Markdown Formatters

## Changed / Added
1. **Conversational Nested Pipeline (`/03-agent-foundry/yggdrasil_agents/chat_pipeline.py`):**
   - `optimise_user_prompt(text) -> OptimisedPrompt`: pure-Python conversational filler stripper and 1,024-parameter micro-model intent detector.
   - `suggest_conversation_title(text) -> str`: pure-Python conversation title generator (`<= 48` chars).
   - `format_slice_result_markdown(result) -> str`: converts all 8 deterministic tool outputs (`CalculationSolverOutput`, `TableHandlingOutput`, `DataComparisonOutput`, `PdfConverterOutput`, `SmartPdfOutput`, `CodingOptimiserOutput`, `ControlSystemOutput`, `ResearchToolOutput`) into human-readable Markdown tables, equations, and summaries instead of raw JSON dumps.
   - `StudioChatPipeline`:
     - Executes deterministic slices first (`0` LLM tokens when deterministic tools answer the turn).
     - Performs at most **one** streaming LLM synthesis call per turn for conversational/untagged prompts, injecting compact `ProjectContext` (custom instructions + pinned notes), recent conversation history, and deterministic summaries.
     - Enforces strict air-gap privacy: when `project.air_gapped=True`, `local_only=True`, or PII/vault taint is detected, cloud Gemini calls are blocked (`air_gap_enforced=True`).
     - Gracefully falls back (`route="offline_fallback"`) when Ollama is unreachable.
     - Provides a persistent background asyncio loop thread (`start()`, `submit()`, `cancel_current()`, `shutdown()`) for non-blocking GUI execution.
2. **Streaming Engine Methods (`/03-agent-foundry/yggdrasil_agents/{local_engine.py,leaves.py}`):**
   - Added `LocalEngine.stream_chat(messages, model_name=None) -> AsyncIterator[str]` sharing the single resident `AsyncOpenAI` client.
   - Added `LeavesCloudAgent.stream_chat(payload: SanitizedCloudRequest, history=None) -> AsyncIterator[str]` guarded by `_assert_air_gap_cleared`.
