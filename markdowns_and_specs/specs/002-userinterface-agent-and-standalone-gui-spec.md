# Spec 002: Conditional `[/userinterface]` Agent, Tri-Changelog Versioning & Self-Sufficient Studio Distribution

- **Spec ID:** `SPEC-002`
- **Status:** `Approved`
- **Authoring Domain:** `/02-yggdrasil-lab/`
- **Governs Downstream Targets:** `/03-agent-foundry/yggdrasil_agents/ui_agent.py`, `/04-yggdrasil-app/{gui_app.py,dist_sync.py}`, `/Changelog/`, and `C:\AntiGravityFiles\output\`
- **Depends On:** [`000-foundational-architecture-spec.md`](000-foundational-architecture-spec.md), [`001-nested-nano-models-and-deterministic-tools-spec.md`](001-nested-nano-models-and-deterministic-tools-spec.md)

---

## 1. Compiled `<prompt_spec>` (`/prompt-optimiser`)

```xml
<prompt_spec>
  <objective>
    Establish mandatory versioned tri-changelog tracking across original and output directories,
    add an independent conditional [/userinterface] nested agent with visual/GUI handoff gating,
    implement a Gemini-branded Yggdrasil Studio GUI, and export self-sufficient Version 1 and Version 2
    bundles into C:\AntiGravityFiles\output\.
  </objective>
  <target_directory>
    /02-yggdrasil-lab/specs/002-userinterface-agent-and-standalone-gui-spec.md
    -> /03-agent-foundry/yggdrasil_agents/ui_agent.py
    -> /04-yggdrasil-app/{gui_app.py,dist_sync.py}
    -> /Changelog/ & C:\AntiGravityFiles\output\
  </target_directory>
  <constraints>
    - Law 1 (Spec-First Gate): All UI agent, GUI, and distribution symbols MUST conform to SPEC-002.
    - Law 3 (Single Local Model): UI agent executes deterministically (0 LLM tokens, 0 VRAM) and shares LocalEngine when invoking nano models inside the Studio GUI.
    - Law 4 (Air-Gap Privacy): personal_vault.db stays local inside data_and_vaults/ and NEVER leaves the machine.
    - Law 6 (Mandatory Tri-Changelog & Backup Sync): Every instruction touching the system MUST record versioned entries in MasterChangelog, YggrdasilChangelog, and EmbedAgentChangelog, first in MasterAgent then synced into output/Version X/.
    - Law 7 ([/userinterface] Conditional UI Gate): UserInterfaceNestedAgent activates directly ONLY when [/userinterface] (or /userinterface) is present or user_confirmed_handoff=True. Visual/GUI keywords without [/userinterface] MUST return a handoff confirmation request before executing UI mutations.
  </constraints>
  <logic_rules>
    IF "[/userinterface]" IN prompt OR "/userinterface" IN prompt OR user_confirmed_handoff == True
      THEN ACTIVATE UserInterfaceNestedAgent -> status="executed"
    ELSE IF any(kw in prompt_words for kw in VISUAL_GUI_KEYWORDS)
      THEN HALT UI EXECUTION -> status="handoff_confirmation_required" AND ASK "Visual/GUI keywords detected; hand over to [/userinterface]?"
    ELSE
      status="no_ui_action"
  </logic_rules>
  <verification_criteria>
    - pytest verifies conditional gate (visual keyword blocks pending confirmation; [/userinterface] executes).
    - Standalone self-sufficiency test executes C:\AntiGravityFiles\output\Version 2\executables\yggdrasil_studio.py --self-test from Version 2 working directory without MasterAgent on PYTHONPATH.
    - All Version 1 (0.1) and Version 2 (0.1 & 0.2) changelogs are populated and non-empty.
  </verification_criteria>
</prompt_spec>
```

---

## 2. Mandatory Tri-Changelog Versioning Protocol (Law 6)

Every substantive instruction follows the **Original -> Changelog -> Output Copy** pipeline:
1. Apply changes inside `c:\AntiGravityFiles\MasterAgent\`.
2. Record versioned deltas in `c:\AntiGravityFiles\MasterAgent\Changelog\`:
   - `MasterChangelog<ver>.md` (Master Orchestrator laws, specs, skills, subagents, routing)
   - `YggrdasilChangelog<ver>.md` (`04-yggdrasil-app` GUI, vaults, references, launchers, output packaging)
   - `EmbedAgentChangelog<ver>.md` (`03-agent-foundry` `yggdrasil_agents`, `ThousandParamMicroModel`, `yggdrasil-nano`, `UserInterfaceNestedAgent`, deterministic tools)
3. Sync self-sufficient prototype/release artifacts and changelogs into `C:\AntiGravityFiles\output\Version <N>\`.

---

## 3. Conditional Nested `[/userinterface]` Agent (`ui_agent.py`)

### 3.1 Keyword & Activation Matrix
- **`VISUAL_GUI_KEYWORDS`:** `{"gui", "visual", "interface", "appearance", "animation", "theme", "window", "layout", "styling", "qol", "frontend", "button", "dark mode"}`
- **`UiHandoffDecision(BaseModel)`:**
  - `explicit_command_detected: bool`
  - `visual_keywords_detected: list[str] = Field(default_factory=list)`
  - `can_execute_ui_agent: bool`
  - `requires_handoff_confirmation: bool`
  - `handoff_prompt: str = ""`
- **`UiThemeSpec(BaseModel)`:**
  - `brand_name: str = "Yggdrasil Studio"`
  - `tagline: str = "Hybrid Local-to-Cloud Sovereign AI"`
  - `accent_primary: str = "#38bdf8"`
  - `accent_secondary: str = "#8b5cf6"`
  - `accent_vault: str = "#10b981"`
  - `background_canvas: str = "#070b14"`
  - `surface_panel: str = "#111827"`
  - `animation_duration_s: float = Field(default=3.5, gt=0.0)`
  - `compact_mode: bool = False`
- **`UiAgentInput(BaseModel)`:**
  - `request_id: str = Field(min_length=1)`
  - `raw_instruction: str = Field(min_length=1)`
  - `user_confirmed_handoff: bool = False`
  - `theme_overrides: dict[str, str] = Field(default_factory=dict)`
- **`UiAgentOutput(BaseModel)`:**
  - `request_id: str`
  - `status: Literal["executed", "handoff_confirmation_required", "no_ui_action"]`
  - `handoff_decision: UiHandoffDecision`
  - `theme: UiThemeSpec`
  - `generated_html_preview: str = ""`
  - `qol_features_enabled: list[str] = Field(default_factory=list)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

---

## 4. Gemini-Branded Yggdrasil Studio GUI (`gui_app.py`) & Self-Sufficient Output Topology

### 4.1 Studio GUI Architecture
- Built using Python stdlib (`http.server.ThreadingHTTPServer`, `webbrowser`, optional `tkinter` desktop shell launcher) + pure HTML5/CSS3/SVG + local deterministic JSON API (`/api/dispatch`, `/api/state`, `/api/changelogs`, `/api/user-content`, `/api/ui-gate`, `/api/svg-tree`).
- Zero external CDN dependencies so the UI renders identically offline and air-gapped.
- Gemini-inspired centered conversational prompt canvas + quick-action tag pills (`#TABLE_DATA`, `#CALC_SOLVE`, `#DATA_COMPARE`, `#PDF_CONVERT`, `#SMART_PDF_LINK`, `#CODE_OPTIMISE`, `#CONTROL_SYSTEM`, `#RESEARCH_GAP`, `[/userinterface]`), left navigation drawer (Sessions, Agents & LMs, Vaults & Data, Changelogs, User Content), and right live animated $W_i$ Yggdrasil SVG Tree + telemetry inspector.

### 4.2 Self-Sufficient `C:\AntiGravityFiles\output\` Folder Structure
```text
C:\AntiGravityFiles\output\
├── Launch-Yggdrasil.bat                  # One-click launcher targeting Version 2
├── Launch-Yggdrasil.ps1                  # PowerShell launcher targeting Version 2
├── README.md                             # Version guide & rollback instructions
├── Version 1\                            # v0.1.0 Baseline Backup & Prototype
│   ├── Changelog\                        # *Changelog0.1.md
│   ├── agents_and_lms\
│   ├── data_and_vaults\
│   ├── executables\
│   └── markdowns_and_specs\
└── Version 2\                            # v0.2.0 Self-Sufficient Studio Release
    ├── Launch-Yggdrasil-Studio.bat       # Launches Version 2 Studio GUI directly
    ├── Launch-Yggdrasil-Studio.ps1
    ├── Changelog\                        # 0.1 & 0.2 changelogs + CHANGELOG_INDEX.md
    ├── agents_and_lms\                   # Self-contained yggdrasil_agents/ + Modelfile + weights JSON
    ├── executables\                      # yggdrasil_studio.py (self-contained GUI + CLI) + app.py + exported_nano_agents.py
    ├── data_and_vaults\                  # personal_vault.db, state_tree.db, references.json, .env.example
    ├── markdowns_and_specs\              # AGENTS.md, PROJECT_STATE.md, specs/, grounding logs
    └── user_content\                     # Antigravity/Gemini-style user data layout
        ├── brain\                        # Session artifacts, SVG previews, reports
        ├── instructions\                 # Custom user prompts, tag templates, .agents snapshot
        ├── exports\                      # Exported manifests & model snapshots
        └── workspaces\                   # Drop-in PDF/CSV/code inputs
```
