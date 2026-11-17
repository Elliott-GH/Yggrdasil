# Embed & Nested Agents Changelog — Version 0.1.0

- **Version:** `0.1.0`
- **Date:** `2026-11-16`
- **Scope:** `/03-agent-foundry/` (`yggdrasil_agents` Package, Ollama `yggdrasil-nano`, 1K Micro-Router & 8 Deterministic Tools)

## Added
1. **Core Tree & Single-VRAM Local Engine:**
   - `local_engine.py`: Singleton `LocalEngine` supporting Ollama (`http://localhost:11434/v1`) and LM Studio (`http://localhost:1234/v1`), configuring `NativeOutput` structured decoding for Ollama.
   - `roots.py`, `trunk.py`, `twigs.py`, `leaves.py`: Four-tier tree agents with $W_i(t) = W_{i,0} e^{-\lambda_i \Delta t} + \alpha R_i$ decay math and `PermissionError` cloud air-gap enforcement.
2. **Pre-Grouped Tag Slicer & 1,024-Parameter CPU Micro-Router:**
   - `pre_slicer.py`: Zero-token single-pass `pre_group_prompt` partitioning raw prompts into isolated `DataSlice` objects (`PreGroupedBundle`) with PII lexical taint propagation.
   - `micro_model.py`: Pure-Python `ThousandParamMicroModel` with exact `1,024` parameters (`768 + 16 + 224 + 14 + 2`), 48-dim `blake2b` + structural feature extractor (`0.0854 ms` avg inference, `0` VRAM).
3. **Callable Ollama Nano Agent & Orchestrator:**
   - `modelfiles/Modelfile.yggdrasil-nano`: Built `yggdrasil-nano:latest` (`FROM qwen2.5:0.5b`, `397 MB`, `temperature 0.1`, `num_ctx 2048`).
   - `nano_agent.py`: `NestedCallableLightAgent` operating strictly on single isolated `DataSlice` payloads via `LocalEngine.get_shared()`.
   - `orchestrator.py` & `nano_models.py`: `NestedModelOrchestrator` executing deterministic-first `IF/THEN/ELSE` dispatch with air-gap taint blocking before semantic escalation.
4. **All 8 Pure-Python Deterministic Solver Functions (`deterministic_tools.py`):**
   - `data_handling_function`, `calculation_solver_function`, `data_comparison_function`, `pdf_converter_function`, `smart_pdf_handling_function`, `coding_optimiser_function`, `control_system_optimiser_function`, `research_tool_function`.
