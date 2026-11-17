# Spec 004: Version 4 Gemini-Style Studio (PySide6), Projects & Conversations, Nested Chat Pipeline

- **Spec ID:** `SPEC-004`
- **Status:** `Approved` (user approved `[/userinterface]` handoff, PySide6, nested routing, Projects = Gemini "Notebooks" slot on 2026-11-17)
- **Authoring Domain:** `/02-yggdrasil-lab/` & `[/userinterface]` (`07-userinterface-architect`)
- **Governs:** `/03-agent-foundry/yggdrasil_agents/{chat_pipeline.py,local_engine.py,leaves.py,orchestrator.py,__init__.py}`, `/04-yggdrasil-app/studio/**`, `/04-yggdrasil-app/YggdrasilStudio.pyw`, `/04-yggdrasil-app/dist_sync.py`, `C:\AntiGravityFiles\output\Version 4\`
- **Depends On:** `SPEC-001` (pre-slicer, micro-model, deterministic tools), `SPEC-002` (UI gate, changelogs), `SPEC-003` (Smart PDF engine)

---

## 1. Why Version 4

V3 dumped raw orchestrator JSON into a tkinter text box. The user's original goal is a **Gemini-like conversational app**: one prompt screen, natural language in, readable answers out, with the nested pipeline (optimiser → tagger → deterministic tools → tiny local model → cloud only when allowed) running *behind* the chat. Conversations and **Projects** (general context groups) are stored locally.

The UI copies Gemini's **general format, not its exact content** (user instruction): collapsible left sidebar, centred greeting + pill composer on a dark background with a soft blue radial glow, suggestion chips, model picker in the composer, conversation list in the sidebar, and a Projects section where Gemini shows "Notebooks".

---

## 2. Agent Package Contracts (`/03-agent-foundry/yggdrasil_agents/chat_pipeline.py`)

All models are Pydantic `BaseModel`. Exported from `yggdrasil_agents.__init__`.

```python
ChatRole = Literal["user", "assistant", "system"]
TurnRoute = Literal["deterministic", "local_llm", "cloud", "mixed", "offline_fallback"]

class ChatHistoryMessage(BaseModel):
    role: ChatRole
    content: str

class ProjectContext(BaseModel):
    project_id: str | None = None
    name: str = ""
    instructions: str = ""          # custom instructions for every chat in the project
    pinned_notes: list[str] = []    # pinned notes / file excerpts, already trimmed by the app
    air_gapped: bool = False        # True => never send anything from this project to cloud

class OptimisedPrompt(BaseModel):
    original: str
    optimised_text: str             # filler stripped, whitespace normalised
    removed_filler: list[str]
    detected_intents: list[str]     # TagType values predicted by the micro-model, e.g. "#CALC_SOLVE"

class PipelineStage(BaseModel):
    name: str                       # "optimise", "tag", "deterministic", "local_llm", "cloud", "compose"
    detail: str
    latency_ms: float = 0.0

class ChatTurnRequest(BaseModel):
    turn_id: str
    user_text: str = Field(min_length=1)
    history: list[ChatHistoryMessage] = []
    project: ProjectContext | None = None
    model_choice: str = "auto"      # "auto" | "<ollama model name>" | "gemini-cloud"
    local_only: bool = False
    attachments: list[str] = []     # absolute file paths (PDF/Office/CSV/TXT)

class ChatTurnResult(BaseModel):
    turn_id: str
    answer_markdown: str
    route: TurnRoute
    model_used: str | None = None
    tags_detected: list[str] = []
    stages: list[PipelineStage] = []
    deterministic_hits: int = 0
    llm_tokens_used: int = 0        # estimate (chars/4) when the server does not report usage
    air_gap_enforced: bool = False
    suggested_title: str | None = None
    error: str | None = None

class ChatPipelineConfig(BaseModel):
    default_local_model: str = "qwen2.5:0.5b"
    ollama_base_url: str = "http://localhost:11434/v1"
    gemini_model: str = "gemini-2.5-flash"
    history_window: int = 12
    references_json_path: str | None = None

def optimise_user_prompt(text: str) -> OptimisedPrompt: ...       # pure Python, no LLM
def suggest_conversation_title(text: str) -> str: ...            # pure Python, <= 48 chars
def format_slice_result_markdown(result: SliceExecutionResult) -> str: ...  # per-tool readable markdown

class StudioChatPipeline:
    def __init__(self, config: ChatPipelineConfig | None = None) -> None: ...
    def list_local_models(self) -> list[str]: ...    # sync, Ollama /api/tags; [] if offline
    def cloud_available(self) -> bool: ...           # GEMINI_API_KEY set and google-genai importable
    async def run_turn(self, request: ChatTurnRequest,
                       on_token: Callable[[str], None] | None = None) -> ChatTurnResult: ...
    # Thread-safe facade for GUI threads: owns ONE background asyncio loop thread.
    def start(self) -> None: ...
    def submit(self, request: ChatTurnRequest,
               on_token: Callable[[str], None] | None = None) -> concurrent.futures.Future[ChatTurnResult]: ...
    def cancel_current(self) -> None: ...
    def shutdown(self) -> None: ...
```

### 2.1 Turn algorithm (deterministic-first, token-conserving)
1. **Optimise** (`optimise_user_prompt`): strip conversational filler, normalise whitespace. No LLM.
2. **Tag** (`pre_group_prompt`, micro-model): explicit `#TAG` blocks and auto-tagged untagged blocks. Attachments add slices (`.pdf` → `#PDF_CONVERT source_path=...`; CSV/TXT tables → `#TABLE_DATA`). `from_personal_vault = project.air_gapped`.
3. **Deterministic**: deterministic-tag slices run through `NestedModelOrchestrator` (cloud disabled). Each result is rendered by `format_slice_result_markdown` (readable summary, never a raw JSON dump; a compact JSON code block is allowed only as a collapsible "details" fallback).
4. **Converse** (only if any `#SEMANTIC_MICRO` / `#GENERAL_SYNTHESIS` content remains, or there were zero deterministic hits): ONE LLM call with a compact context = project instructions + pinned notes + last `history_window` messages + *summaries* of deterministic results (not the raw data). No per-slice nano calls during chat turns.
   - Cloud (`gemini-cloud`, or `auto` when `cloud_available()`) **only if** `not local_only and not project.air_gapped and not bundle.contains_personal_vault_data`, and only via `SanitizedCloudRequest` (Law 4). Otherwise local.
   - Local: `LocalEngine` shared instance (Law 3), streamed via a new public `LocalEngine.stream_chat(messages, model_name=None) -> AsyncIterator[str]`. Switching model = `reset_shared()` then `get_shared(new_config)`.
   - Cloud: new `LeavesCloudAgent.stream_chat(payload: SanitizedCloudRequest, history: list[ChatHistoryMessage]) -> AsyncIterator[str]` (plain text stream; signature verified against google-genai docs).
5. **Compose**: answer = deterministic sections + LLM text. If the local server is unreachable and nothing deterministic ran, `route="offline_fallback"` with a friendly message telling the user to start Ollama (never an exception in the UI).
6. `suggested_title` set on every turn (pure Python).

---

## 3. App Storage (`/04-yggdrasil-app/studio/store.py`)

SQLite `studio.db` inside the vaults dir (monorepo `04-yggdrasil-app/vaults/`, standalone `data_and_vaults/`). Local-only; content leaves the device only through the pipeline rules above.

Tables: `projects(id, name, instructions, air_gapped, created_at, updated_at)`, `project_notes(id, project_id, title, content, created_at)`, `conversations(id, project_id NULL, title, pinned, created_at, updated_at)`, `messages(id, conversation_id, role, content, meta_json, created_at)`. Foreign keys ON; deleting a project moves its conversations to "no project"; deleting a conversation deletes its messages.

```python
class Project(BaseModel): id, name, instructions, air_gapped: bool, created_at, updated_at
class ProjectNote(BaseModel): id, project_id, title, content, created_at
class Conversation(BaseModel): id, project_id: str | None, title, pinned: bool, created_at, updated_at
class StoredMessage(BaseModel): id, conversation_id, role: ChatRole, content, meta: dict[str, Any], created_at

class StudioStore:
    def __init__(self, db_path: Path) -> None
    # projects
    def create_project(self, name: str, instructions: str = "", air_gapped: bool = False) -> Project
    def update_project(self, project_id: str, *, name: str | None = None,
                       instructions: str | None = None, air_gapped: bool | None = None) -> Project
    def delete_project(self, project_id: str) -> None
    def list_projects(self) -> list[Project]
    def get_project(self, project_id: str) -> Project | None
    def add_note(self, project_id: str, title: str, content: str) -> ProjectNote
    def list_notes(self, project_id: str) -> list[ProjectNote]
    def delete_note(self, note_id: str) -> None
    def build_project_context(self, project_id: str | None) -> ProjectContext | None
    # conversations
    def create_conversation(self, project_id: str | None = None, title: str = "New chat") -> Conversation
    def rename_conversation(self, conversation_id: str, title: str) -> None
    def set_pinned(self, conversation_id: str, pinned: bool) -> None
    def move_conversation(self, conversation_id: str, project_id: str | None) -> None
    def delete_conversation(self, conversation_id: str) -> None
    def get_conversation(self, conversation_id: str) -> Conversation | None
    def list_conversations(self, project_id: str | None = None, *, all_projects: bool = True,
                           search: str = "") -> list[Conversation]   # pinned first, then updated_at desc
    # messages
    def add_message(self, conversation_id: str, role: ChatRole, content: str,
                    meta: dict[str, Any] | None = None) -> StoredMessage   # touches updated_at
    def list_messages(self, conversation_id: str) -> list[StoredMessage]
    def history_for_pipeline(self, conversation_id: str, limit: int = 12) -> list[ChatHistoryMessage]
```

---

## 4. UI (`/04-yggdrasil-app/studio/` — PySide6, `[/userinterface]`)

Entry: `04-yggdrasil-app/YggdrasilStudio.pyw` → `studio.app.main(argv)`. `--self-test` runs headless (`QT_QPA_PLATFORM=offscreen`).

**Layout (Gemini general format):**
- **Sidebar** (≈260 px, collapsible to an icon rail with `Ctrl+B`): brand mark + "Yggdrasil", search and collapse icons; `New chat`; tool entries (`PDF Workbench`, `Agents & Pipeline`, `Changelogs`); **Projects** section (`+ New project`, project list, `All projects`); **Chats** list (pinned first, then recent; right-click: Rename, Pin/Unpin, Move to project, Delete); footer: `Settings` and a status row ("Ollama online · qwen2.5:0.5b" / "Offline").
- **Home**: near-black background with a soft dark-blue radial glow, centred greeting "Where should we start?" (inside a project: the project name), pill-shaped composer (`+` attach, placeholder "Ask Yggdrasil", model picker `Auto ▾` listing Auto, local Ollama models, Gemini cloud (disabled with tooltip if no key), send button), and 3 suggestion chips under it.
- **Chat**: centred column (max ≈760 px); user messages as rounded bubbles on the right; assistant messages as rendered markdown on the left, streamed token-by-token; a small route line under each answer ("⚡ 2 tools · 0 tokens · deterministic" / "🦙 qwen2.5:0.5b · local" / "☁ gemini-2.5-flash") that expands to show pipeline stages. Composer docked at the bottom. `Esc` cancels a running turn.
- **Project page**: name, custom-instructions editor, air-gapped toggle, pinned notes (add/delete), conversations in the project, composer that starts a new chat inside the project.
- **PDF Workbench page**: reuses SPEC-003 `SmartPdfWorkbenchEngine` (smart numeric sort, convert, merge, link index).
- **Settings dialog**: default model, local-only mode, Gemini API key status (read from env / `.env`; never stored in `studio.db`), data folder location.
- **Shortcuts**: `Ctrl+N` new chat, `Ctrl+K` search chats, `Ctrl+B` toggle sidebar, `Enter` send, `Shift+Enter` newline, `Esc` cancel.
- **Threading**: GUI never blocks; pipeline runs via `StudioChatPipeline.submit`, tokens marshalled to the GUI thread with Qt signals.

---

## 5. Distribution (`Version 4`)

`dist_sync.py` builds `C:\AntiGravityFiles\output\Version 4\` (`Yggdrasil.pyw`, `YggdrasilAppLauncher.bat/.ps1`, `app-0.4.0/` with `studio/` + `YggdrasilStudio.pyw` + V3 `native_gui.py` for the PDF engine, `agents_and_lms/`, `data_and_vaults/`, `markdowns_and_specs/`, `user_content/`, `resources/`, `logs/`, `Changelog/`, `version`, `YGGDRASIL_BUILD_INFO.txt`), preserves Versions 1–3, and points root launchers to Version 4. Launchers keep the 0.3.1 fixes (no in-block variable expansion; venv self-relaunch; visible error dialog + `logs/launch_error.log`).

## 6. Verification Criteria
- `ruff check` and `mypy --strict` clean on new/changed modules.
- `pytest` for `03-agent-foundry/tests` (existing 12 + new pipeline tests) and `04-yggdrasil-app/tests` (store tests) all pass.
- Pipeline tests cover: optimiser, deterministic-only turn (no LLM), air-gapped project never reaches cloud, offline fallback, title suggestion.
- `YggdrasilStudio.pyw --self-test` (offscreen) creates the window, runs one deterministic turn end-to-end, persists and reloads the conversation, exit code 0.
- Standalone `Version 4` launcher `--self-test` reports `mode="standalone"`.
