# Yggdrasil Project State & Roadmap

> **Last Updated:** 2026-11-17
> **Active Phase:** Phase 4 Active (`v0.5.0` — Gemini Interactive Agentic Workspace (`PySide6` Split-Screen Canvas, Deep Research, Thinking Trace, Gems, Library), Google Antigravity SDK Bridge & `0.5` Tri-Changelog)
> **Active Milestone:** `M2.1` — Formalize full $W_i$ Context-Decay Math & SQLite Vault DAO Migrations in `/02-yggdrasil-lab/specs/`

---

## 1. Architecture Overview

Yggdrasil is a **hybrid local-to-cloud AI ecosystem** structured around a four-tier tree topology and a strict air-gap privacy boundary:

1. **Roots (`yggdrasil_agents.roots`)** — Local ingestion & normalization micro-agents parsing raw notes, tasks, and scientific/ChemEng context using the single shared resident local LLM (`http://localhost:11434/v1` Ollama / `http://localhost:1234/v1` LM Studio).
2. **Trunk (`yggdrasil_agents.trunk`)** — Context-decay math engine computing node priority weights ($W_i$), pruning stale branches, and executing the **Air-Gap Privacy Gate** before any cloud routing.
3. **Twigs (`yggdrasil_agents.twigs`)** — Single-responsibility local micro-agents executing deterministic or private reasoning strictly on-device with Pydantic `BaseModel` validation.
4. **Leaves (`yggdrasil_agents.leaves`)** — Cloud Gemini synthesis layer (`google-genai`) accepting **only** air-gap-cleared `SanitizedCloudRequest` objects (`contains_personal_vault_data=False`).

### Dual Vault & Reference Storage (`/04-yggdrasil-app/vaults/`)
- **`personal_vault.db` (Air-Gapped Local Only):** Private notes, credentials/metadata, personal reflections. **Hard-blocked from Gemini cloud APIs.**
- **`state_tree.db` (Tree State & Decay Weights):** Active Yggdrasil nodes, $W_i$ decay scores, parent-child branch topology, and SVG render telemetry.
- **`references.json` (Domain References):** Public/non-sensitive scientific citations, ChemEng constants, and verified SDK/API documentation links.

---

## 2. Four-Phase Yggdrasil Roadmap

| Phase | Scope | Target Directory | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Monorepo Governance, Customizations (`AGENTS.md`, skills, subagents) & Directory Scaffolding | Root, `/.agents/`, `01`–`04` | **Completed** |
| **Phase 2** | Domain Math ($W_i$ Context-Decay Derivations), ChemEng Models & Animated SVG UI Specifications | `/02-yggdrasil-lab/specs/` | **Active (`SPEC-001`–`SPEC-005` Done)** |
| **Phase 3** | Micro-Agent Foundry Implementation (`LocalEngine`, `roots`, `trunk`, `twigs`, `leaves`, `chat_pipeline`, `agy_bridge`, `SPEC-001`–`005` suite) | `/03-agent-foundry/` | **In Progress (`SPEC-005` AGY Bridge & Deep Research Done)** |
| **Phase 4** | Master Application Integration (SQLite vault & studio managers, Air-Gap runtime guard, Gemini Interactive Workspace + Canvas + Library, Smart PDF Workbench) | `/04-yggdrasil-app/` | **In Progress (`v0.5.0` Gemini Interactive Workspace)** |

---

## 3. Current Status Tracker

### Completed Tasks
- [x] Bootstrapped root governance (`AGENTS.md`, `PROJECT_STATE.md`, `.gitignore`).
- [x] Created 4 workspace skills in `/.agents/skills/` (`prompt-optimiser`, `project-router`, `qa-auditor`, `pm-sync`).
- [x] Created 4 subagent definitions in `/.agents/agents/` and local `AGENTS.md` rulebooks across `01`–`04`.
- [x] Authored foundational Spec `000-foundational-architecture-spec.md` in `/02-yggdrasil-lab/specs/` authorizing initial boilerplate.
- [x] Scaffolded `/01-code-oracle/README.md`, `/03-agent-foundry/` (`pyproject.toml` + `yggdrasil_agents` typed stubs), and `/04-yggdrasil-app/` (`vaults/`, `.env.example`, `app.py`).
- [x] Authored `01-code-oracle/001-nano-routing-and-deterministic-tools-grounding.md` verifying Python 3.11+ `ast`, `math`/`statistics`, `pypdf`, `pydantic` v2, and Ollama `Modelfile` patterns.
- [x] Authored & marked `Status: Approved` Spec `001-nested-nano-models-and-deterministic-tools-spec.md` (`SPEC-001`) in `/02-yggdrasil-lab/specs/` covering `<prompt_spec>`, Pre-Grouped Tag Slicing, `ThousandParamMicroModel` (1,024 params), `NestedCallableLightAgent`, `NestedModelOrchestrator`, `Modelfile.yggdrasil-nano`, and all 8 deterministic Pydantic tool schemas.
- [x] Installed Python 3.12.10 (`.venv`), `yggdrasil-agents` editable package (`pypdf>=4.0.0`), and Ollama v0.40.16 (`qwen2.5:0.5b`, `smollm2:135m`, and custom `yggdrasil-nano:latest` from `Modelfile.yggdrasil-nano`).
- [x] Added `05-nano-tag-dispatcher`, `06-deterministic-solver`, and `nano-dispatcher` skill under `/.agents/`.
- [x] Completed `T3.3`: Implemented `pre_slicer.py`, `micro_model.py`, `nano_agent.py`, `deterministic_tools.py` (all 8 tools), `orchestrator.py`, `nano_models.py`, and `tests/test_nested_nano_and_tools.py` (`10/10` pytest passing, `ruff` & `mypy --strict` clean, live `yggdrasil-nano` inference verified).
- [x] Exported lightweight callable models & tools to `/04-yggdrasil-app/exported_nano_agents.py`, seeded `/04-yggdrasil-app/vaults/references.json` (5 verified entries), and wired `NestedModelOrchestrator` into `/04-yggdrasil-app/app.py`.
- [x] Authored & marked `Status: Approved` Spec `002-userinterface-agent-and-standalone-gui-spec.md` (`SPEC-002`) adding Law 6 (Mandatory Tri-Changelog Versioning) and Law 7 (`[/userinterface]` Conditional UI Agent Gate).
- [x] Added `userinterface` skill (`/.agents/skills/userinterface/SKILL.md`), `07-userinterface-architect` subagent (`/.agents/agents/07-userinterface-architect.md`), and `03-agent-foundry/yggdrasil_agents/ui_agent.py` (`11/11` pytest passing).
- [x] Built Gemini-branded Yggdrasil Studio GUI (`04-yggdrasil-app/gui_app.py`), self-sufficient packager (`04-yggdrasil-app/dist_sync.py`), populated `0.1` & `0.2` changelogs in `/Changelog/`, and synced `Version 1` (`v0.1.0`) & `Version 2` (`v0.2.0`) to `C:\AntiGravityFiles\output\`.
- [x] Authored & marked `Status: Approved` Spec `003-native-desktop-gui-and-pdf-suite-spec.md` (`SPEC-003`), added native `tkinter` theme tokens to `ui_agent.py`, built native Windows desktop `.pyw` software (`04-yggdrasil-app/native_gui.py`, `YggdrasilDesktop.pyw`) with Smart PDF Workbench, verified `12/12` unit tests, documented `0.3` tri-changelogs (`MasterChangelog0.3.md`, `YggrdasilChangelog0.3.md`, `EmbedAgentChangelog0.3.md`), and updated `dist_sync.py` to build `Version 3` (`v0.3.0`) in `C:\AntiGravityFiles\output\`.
- [x] Authored & marked `Status: Approved` Spec `004-gemini-clone-studio-chat-projects-spec.md` (`SPEC-004`), built `chat_pipeline.py` + streaming `local_engine.py`/`leaves.py` (`18/18` foundry tests), built SQLite `studio.db` Projects & Conversations store (`04-yggdrasil-app/studio/store.py`, `5/5` store tests), built Gemini-clone `PySide6` desktop studio (`04-yggdrasil-app/studio/{theme.py,app.py}`, `YggdrasilStudio.pyw`), documented `0.4` tri-changelogs, and packaged `Version 4` (`v0.4.0`) into `C:\AntiGravityFiles\output\`.
- [x] Authored & marked `Status: Approved` Spec `005-gemini-canvas-deep-research-agy-sdk-spec.md` (`SPEC-005`), installed `google-antigravity==0.1.23`, built `agy_bridge.py` + V5 `chat_pipeline.py` (`22/22` foundry tests), extended `studio.db` with `gems` & `artifacts` (`7/7` store tests), co-ran `07-userinterface-architect` (`[/userinterface]`) to build the Split-Screen `CanvasWorkspacePanel`, Universal `+` Menu (`Canvas`, `Deep Research`, `Deep Think`), Collapsible Thinking Trace, `Gems`, `Library`, and Antigravity SDK Hub, documented `0.5` tri-changelogs, and packaged `Version 5` (`v0.5.0`) into `C:\AntiGravityFiles\output\`.

### Pending Backlog
| ID | Task | Target Directory | Priority | Gate / Dependency |
| :--- | :--- | :--- | :--- | :--- |
| `T2.1` | Specify exact $W_i(t)$ exponential/half-life decay parameters & ChemEng branch taxonomy | `/02-yggdrasil-lab/specs/` | High | None |
| `T2.2` | Specify animated Yggdrasil SVG tree layout, node radius/opacity mapping from $W_i$, and UI events | `/02-yggdrasil-lab/specs/` | High | `T2.1` |
| `T2.3` | Specify SQLite schemas & migration rules for `personal_vault.db` and `state_tree.db` | `/02-yggdrasil-lab/specs/` | High | Spec-First Gate |
| `T3.1` | Expand `LocalEngine` & `RootsAgent`/`TrunkRouter` with full `T2.1` decay taxonomy | `/03-agent-foundry/` | Medium | `000` + `T2.1` |
| `T3.2` | Add integration test suite for `RootsAgent`, `TrunkRouter`, `TwigsExecutor`, and `LeavesCloudAgent` | `/03-agent-foundry/` | Medium | `T3.1`, `T2.1` |
| `T4.1` | Implement SQLite vault DAOs & end-to-end air-gap leak tests | `/04-yggdrasil-app/` | Medium | `T2.3`, `T3.2` |
| `T4.2` | Implement animated Yggdrasil SVG tree renderer wired to `state_tree.db` | `/04-yggdrasil-app/` | Low | `T2.2`, `T4.1` |

---

## 4. Cross-Project Dependency Status

| Downstream Consumer | Upstream Dependency | Status | Notes |
| :--- | :--- | :--- | :--- |
| `03-agent-foundry` | `02-yggdrasil-lab/specs/000-foundational-architecture-spec.md` | **Satisfied (Scaffold)** | Foundational spec approved for initial package structure & stubs |
| `03-agent-foundry` | `02-yggdrasil-lab/specs/001-nested-nano-models-and-deterministic-tools-spec.md`, `002`, `003`, `004`, & `005` | **Satisfied (`SPEC-001`–`SPEC-005` Implemented)** | All 8 deterministic tools, 1,024-param micro-router, `NestedCallableLightAgent`, `NestedModelOrchestrator`, `UserInterfaceNestedAgent`, `StudioChatPipeline`, and `AgySdkBridge` tested (`22/22`) |
| `03-agent-foundry` | `02-yggdrasil-lab/specs/` (`T2.1` decay math spec) | **Blocked / Pending** | Needed before full production decay taxonomy in `trunk.py` |
| `04-yggdrasil-app` | `03-agent-foundry` (`yggdrasil_agents` package) | **Ready (Editable Installed)** | `app.py` and `exported_nano_agents.py` import & run `yggdrasil_agents` inside `.venv` |
| `04-yggdrasil-app` | `02-yggdrasil-lab/specs/` (`T2.2`, `T2.3`) | **Pending** | Needed before full vault DAO and SVG UI implementation |
| `01-code-oracle` | Context7 / Google Developer Knowledge / Local Docs | **Ready** | Grounding log `001` verified; ready for ongoing queries across `02`–`04` |
