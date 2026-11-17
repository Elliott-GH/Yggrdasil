# Yggdrasil App Changelog — Version 0.1.0

- **Version:** `0.1.0`
- **Date:** `2026-11-16`
- **Scope:** `/04-yggdrasil-app/` Vault Initialization, Reference Store & Nano Export Registry

## Added
1. **Application Entrypoint (`/04-yggdrasil-app/app.py`):**
   - Initialized SQLite schemas for `vaults/personal_vault.db` (`personal_notes` strictly `air_gapped`) and `vaults/state_tree.db` (`tree_nodes` with $W_i$ context-decay fields).
   - Built `render_yggdrasil_svg_tree(...)` rendering animated SVG roots (emerald `#10b981`) and cloud-eligible leaves (cyan `#38bdf8`) scaled by $W_i$.
   - Wired `LocalEngine`, `RootsAgent`, `TrunkRouter`, `TwigsExecutor`, `LeavesCloudAgent`, and `NestedModelOrchestrator` into `bootstrap_app()`.
2. **Exported Nano Agents Module (`/04-yggdrasil-app/exported_nano_agents.py`):**
   - Exported `EXPORTED_NANO_AGENTS` registry (`10` entries), `get_exported_nano_manifest()`, `load_reference_entries()`, and `run_pre_tagged_workflow()`.
   - Demonstrated 8/8 pre-tagged slices executing deterministically (`0` LLM tokens, `token_savings_ratio=0.8495`, `~3.2 ms` total latency).
3. **Vaults & Configuration:**
   - Seeded `/04-yggdrasil-app/vaults/references.json` with 5 verified ChemEng, control-system, and BM25 citations (`Rivera 1986`, `Skogestad 2003`, `Ziegler-Nichols 1942`, `Perry's`, `Robertson 2009`).
   - Created `/04-yggdrasil-app/.env.example` defaulting `YGGDRASIL_LOCAL_MODEL=yggdrasil-nano` and `STRICT_AIR_GAP=true`.
