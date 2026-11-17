# Spec 000: Yggdrasil Foundational Architecture & Package Contracts

- **Spec ID:** `SPEC-000`
- **Status:** `Approved`
- **Scope:** Authorizes initial scaffolding and typed stubs for `/03-agent-foundry/yggdrasil_agents/` and `/04-yggdrasil-app/`.

---

## 1. System Topology (Four-Tier Hybrid Tree)

Yggdrasil separates private local cognition from sanitized cloud reasoning across four layers:

1. **LocalEngine (`yggdrasil_agents.local_engine`):**
   - Single resident local LLM connection manager supporting **Ollama** (`http://localhost:11434/v1`) and **LM Studio** (`http://localhost:1234/v1`).
   - Enforces single-instance residency (`LocalEngine` singleton / shared client) to prevent concurrent model loading in VRAM.
2. **Roots (`yggdrasil_agents.roots`):**
   - Local context ingestion and classification into typed `RootContextItem` and `RootIngestionOutput` Pydantic models.
3. **Trunk (`yggdrasil_agents.trunk`):**
   - Computes node priority weight $W_i(t)$ via context-decay math:
     $$W_i(t) = W_{i,0} \cdot e^{-\lambda_i \Delta t} + \alpha \cdot R_i$$
     where:
     - $W_{i,0} \ge 0$: initial node priority weight
     - $\lambda_i \ge 0$: decay constant (hours$^{-1}$)
     - $\Delta t \ge 0$: elapsed hours since last activation
     - $\alpha \ge 0$: resonance boost coefficient
     - $R_i \ge 0$: reactivation / reference signal count
   - Enforces the **Air-Gap Privacy Gate**: records originating from `personal_vault.db` or flagged `contains_personal_vault_data=True` are strictly restricted to local `Twigs` execution.
4. **Twigs (`yggdrasil_agents.twigs`):**
   - Single-responsibility local micro-agents sharing `LocalEngine` and returning validated `TwigTaskOutput` schemas.
5. **Leaves (`yggdrasil_agents.leaves`):**
   - Cloud Gemini synthesis layer accepting only `SanitizedCloudRequest` models where `contains_personal_vault_data == False`.
   - Must raise `PermissionError` if any air-gapped or unsanitized payload reaches the cloud boundary.

---

## 2. Vault Architecture (`/04-yggdrasil-app/vaults/`)

- **`personal_vault.db`:** Air-gapped SQLite store (`personal_notes` table). Strictly local; never forwarded to `leaves.py`.
- **`state_tree.db`:** Tree node topology and $W_i$ vitality state (`tree_nodes` table).
- **`references.json`:** Non-sensitive scientific/ChemEng citations and documentation references.

---

## 3. Acceptance Criteria for Foundational Scaffold

1. `yggdrasil_agents` installs cleanly via `pyproject.toml` (`requires-python >= 3.11`).
2. All micro-agent inputs and outputs inherit from `pydantic.BaseModel`.
3. `LeavesCloudAgent` enforces a runtime air-gap guard raising `PermissionError` on tainted input.
4. `04-yggdrasil-app/app.py` imports `yggdrasil_agents`, initializes local SQLite schemas in `vaults/`, reads `references.json`, and exposes a typed animated SVG tree stub.
