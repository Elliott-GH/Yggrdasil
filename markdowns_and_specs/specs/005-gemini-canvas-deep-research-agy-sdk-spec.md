# Spec 005: Version 5 Gemini Interactive Workspace (Canvas, Deep Research, Thinking Trace, Gems, Library & Google Antigravity SDK Bridge)

- **Spec ID:** `SPEC-005`
- **Status:** `Approved` (user confirmed `[/userinterface]` co-execution + full researched Gemini capabilities + `/google-antigravity-sdk` integration on 2026-11-17)
- **Authoring Domain:** `/02-yggdrasil-lab/` & `[/userinterface]` (`07-userinterface-architect`)
- **Governs:**
  - `/03-agent-foundry/yggdrasil_agents/{agy_bridge.py,chat_pipeline.py,__init__.py,nano_models.py}`
  - `/03-agent-foundry/tests/test_agy_and_v5_pipeline.py`
  - `/04-yggdrasil-app/studio/{store.py,theme.py,app.py,__init__.py}`
  - `/04-yggdrasil-app/YggdrasilStudio.pyw`, `/04-yggdrasil-app/dist_sync.py`
  - `/Changelog/*0.5.md` and `C:\AntiGravityFiles\output\Version 5\`
- **Depends On:** `SPEC-001`–`SPEC-004`

---

## 1. Objective & Researched Gemini UI Capabilities

Version 5 (`v0.5.0`) upgrades **Yggdrasil Sovereign Studio** from a chat-only window into a complete **Gemini Interactive Agentic Workspace** in native `PySide6`, co-engineered by `03-agent-foundry`, `04-yggdrasil-app`, and `07-userinterface-architect` (`[/userinterface]`):

1. **Split-Screen Interactive `Canvas` Panel (Side-by-Side Co-Editor & Preview):**
   - Right-hand collapsible `QSplitter` workspace beside the conversation column.
   - Displays code, Markdown reports, Deep Research syntheses, or tabular outputs in an interactive editor (`Edit Source` tab + rendered `Live Preview` tab).
   - Quick Canvas AI / Deterministic transformation bar: `Refine / Clean`, `Format Markdown Table`, `AST Optimize Python Code`, `Copy`, `Save to Library`, and `Export (.md / .py / .html / .pdf)`.
2. **Universal `+` Composer Menu & Active Mode Pills:**
   - Clicking `+` in the rounded pill composer opens a structured Gemini-style popup menu:
     - `📎 Upload Files (PDF, Office, CSV, Python, Markdown)`
     - `📝 Open / Send to Canvas` (auto-opens the response in the split-screen Canvas)
     - `🔬 Deep Research` (activates multi-step Deep Research mode: builds an explicit investigation plan, queries local verified references + deterministic solvers + local/AGY synthesis, and produces a cited report directly into Canvas)
     - `🧠 Deep Think (Reasoning Trace)` (expands internal deliberation & step-by-step routing/math trace)
     - `📄 Smart PDF Merge & Link`
   - Active composer modes (`Canvas`, `Deep Research`, `Deep Think`) appear as removable pill chips inside the composer bar alongside file attachments.
3. **Collapsible `"Show Thinking & Routing Trace"` Accordion:**
   - Every assistant message includes a collapsible Gemini-style **Thinking & Routing Trace** drawer above the answer showing:
     - Prompt optimisation diff (original vs. stripped filler),
     - 1,024-parameter micro-model tag predictions & $W_i$ context-decay weights,
     - Deterministic solver steps, AGY SDK tool invocations, and per-stage latency.
4. **Gems (Reusable Custom Personas) + Projects ("Notebooks") + Artifact Library:**
   - **Gems** section in the left sidebar (`💎 Gems`): pre-seeded and user-creatable specialist personas (e.g., *ChemEng Process Architect*, *Python AST Optimizer*, *Control Loop Tuner*, *Deep Research Analyst*) with custom system instructions and preferred tools.
   - **Library** view (`📚 Library` in the sidebar): persistent catalog of all saved Canvas documents, Deep Research reports, and merged PDFs stored in `studio.db` (`artifacts` table).
5. **Per-Message Action Bar:**
   - Beneath every assistant reply: `📝 Open in Canvas`, `📋 Copy`, `🔄 Regenerate`, `💾 Save to Library`, and `🔍 Toggle Thinking`.
6. **Google Antigravity SDK (`/google-antigravity-sdk`) Integration (`agy_bridge.py`):**
   - Implements the Google Antigravity SDK (`google.antigravity`) patterns from `google-antigravity-sdk`:
     - **Local Ollama / LM Studio (`LocalOpenAIAgentConfig`):** `LocalOpenAIAgentConfig(model=..., base_url="http://localhost:11434/v1").lightweight()` equipped with Yggdrasil's deterministic Python tools (`solve_calculation`, `analyse_table`, `tune_pid_controller`, `optimise_python_code`, `verify_research_gaps`) and `app_data_dir` pointed to `user_content/brain`.
     - **Hosted Gemini (`LocalAgentConfig`):** When `GEMINI_API_KEY` is configured and the project/turn is **not** air-gapped (`contains_personal_vault_data=False`), supports `LocalAgentConfig` with `BudgetConfig` and `CompactionConfig`, plus setup guidance pointing to `https://aistudio.google.com/app/api-keys`.
     - **Seamless Runtime Fallback:** If the `google-antigravity` package or `localharness` binary is not installed in the current environment, `AgySdkBridge` transparently executes the same custom tool & streaming agent contract via `LocalEngine` so the app works 100% offline out-of-the-box.

---

## 2. Agent Package Contracts (`/03-agent-foundry/yggdrasil_agents/`)

### 2.1 `agy_bridge.py`
```python
AgyBackendMode = Literal["local_openai", "hosted_gemini", "lite_rt"]

class AgyBridgeConfig(BaseModel):
    backend_mode: AgyBackendMode = "local_openai"
    model_name: str = "yggdrasil-nano"
    base_url: str = "http://localhost:11434/v1"
    app_data_dir: str | None = None
    max_model_calls: int = 6
    max_tool_calls: int = 10
    max_total_tokens: int = 32_000
    token_compaction_threshold: int = 24_000
    system_instructions: str = ""

class AgyBridgeStatus(BaseModel):
    sdk_installed: bool
    backend_mode: AgyBackendMode
    model_name: str
    base_url: str
    gemini_api_key_configured: bool
    api_key_setup_url: str = "https://aistudio.google.com/app/api-keys"
    equipped_tools: list[str]
    config_preview_code: str

class DeepResearchSection(BaseModel):
    heading: str
    content_markdown: str
    citations: list[str] = []

class DeepResearchReport(BaseModel):
    query: str
    title: str
    investigation_plan: list[str]
    sections: list[DeepResearchSection]
    verified_references: list[str]
    deterministic_findings: list[str]
    markdown_document: str
    air_gap_enforced: bool = True

class AgySdkBridge:
    def __init__(self, config: AgyBridgeConfig | None = None) -> None: ...
    def status(self) -> AgyBridgeStatus: ...
    def build_sdk_config_snippet(self) -> str: ...
    async def run_agent_turn(
        self,
        prompt: str,
        *,
        air_gapped: bool = True,
        on_token: Callable[[str], None] | None = None,
    ) -> str: ...
    async def run_deep_research(
        self,
        query: str,
        *,
        local_references: list[ReferenceEntry] | None = None,
        project_instructions: str = "",
        air_gapped: bool = True,
    ) -> DeepResearchReport: ...
```

### 2.2 `chat_pipeline.py` Extensions (Backwards-Compatible)
- `ChatTurnRequest` adds optional fields with defaults:
  - `deep_research: bool = False`
  - `thinking_mode: bool = False`
  - `open_in_canvas: bool = False`
  - `gem_name: str | None = None`
  - `gem_instructions: str = ""`
- `ChatTurnResult` adds optional fields with defaults:
  - `thinking_trace_markdown: str = ""` (structured step-by-step trace of optimisation, micro-model tag logits/weights, $W_i$, and tool execution)
  - `canvas_title: str | None = None`
  - `canvas_content: str | None = None` (populated automatically when `open_in_canvas=True`, `deep_research=True`, or when code/table/report artifacts are produced)
  - `canvas_kind: Literal["markdown", "code", "html", "report"] = "markdown"`
  - `citations: list[str] = []`

---

## 3. Storage Extensions (`/04-yggdrasil-app/studio/store.py`)

`StudioStore` adds two tables to `studio.db` (preserving all `SPEC-004` tables and methods):
1. `gems(id, name, icon, description, instructions, default_mode, created_at)`:
   - Models: `Gem(BaseModel)` with `id`, `name`, `icon`, `description`, `instructions`, `default_mode` (`"chat" | "canvas" | "deep_research" | "thinking"`), `created_at`.
   - Methods: `create_gem(...) -> Gem`, `list_gems() -> list[Gem]`, `get_gem(gem_id) -> Gem | None`, `delete_gem(gem_id) -> None`.
   - `seed_defaults_if_empty()` seeds 4 built-in Gems:
     - `⚗️ ChemEng Process Architect`
     - `🐍 Python AST & Code Optimizer`
     - `🎛️ PID & Control Loop Tuner`
     - `🔬 Deep Research & Theory Verifier`
2. `artifacts(id, conversation_id, project_id, title, kind, content, created_at, updated_at)`:
   - Models: `CanvasArtifact(BaseModel)` with `id`, `conversation_id`, `project_id`, `title`, `kind` (`"markdown" | "code" | "html" | "report"`), `content`, `created_at`, `updated_at`.
   - Methods: `save_artifact(...) -> CanvasArtifact`, `update_artifact(artifact_id, *, title=None, content=None) -> CanvasArtifact`, `list_artifacts(project_id=None) -> list[CanvasArtifact]`, `get_artifact(artifact_id) -> CanvasArtifact | None`, `delete_artifact(artifact_id) -> None`.

---

## 4. UI Architecture (`/04-yggdrasil-app/studio/app.py` & `theme.py`)

Co-implemented with `07-userinterface-architect` (`[/userinterface]`):
1. **Main Central Split View (`QSplitter`):**
   - Left pane: Greeting / Active Conversation stream + bottom pill composer.
   - Right pane (`CanvasWorkspacePanel`, collapsible, opens automatically when `open_in_canvas` / `deep_research` triggers or when clicking `📝 Open in Canvas` on any message or opening an item from `📚 Library`):
     - Header: editable artifact title, kind badge (`Markdown`, `Code`, `Report`, `HTML`), close `✕` button.
     - Tabs: `✏️ Co-Editor` (monospace/prose editor) and `👁️ Live Preview` (rendered Markdown/HTML/Table view).
     - Action toolbar: `✨ Refine`, `📐 Format Table`, `⚡ AST Optimize Code`, `💾 Save to Library`, `📤 Export (.md/.py/.html)`, `📋 Copy`.
2. **Universal `+` Popup Menu & Mode Chips in `PillComposerWidget`:**
   - `+` button opens a sleek dark `QMenu` with:
     - `📎 Attach Files...`
     - `📝 Canvas Mode (Co-Edit in Split View)` (checkable)
     - `🔬 Deep Research Mode (Multi-Step Investigation)` (checkable)
     - `🧠 Deep Think Mode (Reasoning Trace)` (checkable)
     - `📄 Open PDF Workbench`
   - Active modes render as glowing pill chips in the composer bar.
   - Model selector includes `Auto (Nested Router)`, `AGY Local Agent (Ollama)`, `yggdrasil-nano`, `qwen2.5:0.5b`, `smollm2:135m`, and `Gemini Cloud (AGY / Leaves)`.
3. **Collapsible Thinking & Routing Trace in `AssistantMessageCard`:**
   - Toggle button `🧠 Show Thinking & Routing Trace (N stages)` that expands/collapses the step-by-step deliberation, prompt optimisation diff, and $W_i$ weights above the assistant's Markdown answer.
   - Bottom action row: `📝 Open in Canvas`, `📋 Copy`, `🔄 Regenerate`, `💾 Save to Library`.
4. **Sidebar Additions:**
   - `📚 Library` navigation button opening `ArtifactLibraryView` (browse, search, preview, reopen in Canvas, or delete saved artifacts).
   - `🤖 Antigravity SDK` status & code generator tab inside `Pipeline & Agents` showing `AgySdkBridge.status()`, `https://aistudio.google.com/app/api-keys` setup helper, and ready-to-run `LocalOpenAIAgentConfig` / `LiteRTAgentConfig` / `LocalAgentConfig` snippets.
   - `💎 Gems` collapsible section in the sidebar above `Projects` (clicking a Gem scopes the composer to that Gem's specialist instructions & default mode; `+` creates a custom Gem).
5. **Headless `--self-test` (`run_studio_self_test`):**
   - Verifies V5 end-to-end: creates a Project, selects a Gem, runs a deterministic + Canvas turn AND a Deep Research turn, verifies the `CanvasWorkspacePanel` populates, verifies `thinking_trace_markdown` is generated, saves the Canvas artifact to `Library` (`artifacts` table in `studio.db`), checks `AgySdkBridge.status()`, and writes `user_content/brain/studio_v5_self_test.json`.
