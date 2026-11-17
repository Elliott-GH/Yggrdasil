# Master Agent Changelog — Version 0.1.0

- **Version:** `0.1.0`
- **Date:** `2026-11-16`
- **Scope:** Monorepo Governance, Customizations, Engineering Laws & Multi-Agent Architecture

## Added
1. **Root Master Governance & State Tracker:**
   - Created `/AGENTS.md` defining the Master Orchestrator identity and **5 Core Engineering Laws** (Spec-First Gate, Zero-Hallucination Grounding, Single-Responsibility Local Micro-Agents, Strict Air-Gap Privacy, Automatic State Tracking).
   - Created `/PROJECT_STATE.md` with the 4-phase Yggdrasil roadmap, dependency tracker, and backlog table.
   - Created `/.gitignore` protecting `.env`, `*.db`, SQLite sidecars, and cache artifacts.
2. **Modular Workspace Skills (`/.agents/skills/`):**
   - `prompt-optimiser/SKILL.md`: Compiles conversational requests into `<prompt_spec>` XML + `IF/THEN/ELSE` boolean logic.
   - `project-router/SKILL.md`: Routes tasks across `01`–`04`, enforces directory isolation & Spec-First Gate.
   - `qa-auditor/SKILL.md`: Audits Spec Alignment, Pydantic `BaseModel` safety, Single-VRAM/async discipline, and Air-Gap privacy.
   - `pm-sync/SKILL.md`: Reconciles `/PROJECT_STATE.md` against filesystem/git diffs.
   - `nano-dispatcher/SKILL.md`: Prioritizes pure-Python deterministic tools and isolated `DataSlice` routing over heavy LLMs.
3. **Subagent Definitions & Local Directory Rules (`/.agents/agents/` + `<sub-project>/AGENTS.md`):**
   - `01-code-oracle`, `02-yggdrasil-lab`, `03-agent-foundry`, `04-yggdrasil-app`, `05-nano-tag-dispatcher`, `06-deterministic-solver`.
4. **Authoritative Specifications (`/02-yggdrasil-lab/specs/` & `/01-code-oracle/`):**
   - Approved `SPEC-000` (`000-foundational-architecture-spec.md`) and `SPEC-001` (`001-nested-nano-models-and-deterministic-tools-spec.md`).
   - Verified SDK/stdlib grounding log `01-code-oracle/001-nano-routing-and-deterministic-tools-grounding.md`.
5. **Local Runtime Installation:**
   - Installed Python `3.12.10` (`.venv`), package dependencies (`pydantic`, `pydantic-ai`, `openai`, `google-genai`, `httpx`, `pypdf`, `pytest`, `ruff`, `mypy`), and Ollama `v0.40.16`.

## Verification Baseline
- `ruff check`: All checks passed.
- `mypy --strict`: 14 source files clean.
- `pytest`: 10/10 unit tests passed.
