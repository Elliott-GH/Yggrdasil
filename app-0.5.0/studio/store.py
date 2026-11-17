"""Local SQLite storage (`studio.db`) for Yggdrasil Studio Projects, Notes, and Conversations."""

from __future__ import annotations

import importlib
import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from studio.paths import ensure_agents_on_path, resolve_studio_paths

ensure_agents_on_path(resolve_studio_paths())

ChatRole = Literal["user", "assistant", "system"]
GemMode = Literal["chat", "canvas", "deep_research", "thinking"]
ArtifactKind = Literal["markdown", "code", "html", "report"]


class ChatHistoryMessage(BaseModel):
    """Chat history message matching `SPEC-004` Section 2."""

    role: ChatRole
    content: str


class ProjectContext(BaseModel):
    """Project context matching `SPEC-004` Section 2."""

    project_id: str | None = None
    name: str = ""
    instructions: str = ""
    pinned_notes: list[str] = Field(default_factory=list)
    air_gapped: bool = False


def _resolve_chat_history_cls() -> type[ChatHistoryMessage]:
    """Return `yggdrasil_agents.ChatHistoryMessage` if available, else local class."""
    try:
        mod = importlib.import_module("yggdrasil_agents")
        cls = getattr(mod, "ChatHistoryMessage", None)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            return cast("type[ChatHistoryMessage]", cls)
    except ImportError:
        pass
    return ChatHistoryMessage


def _resolve_project_context_cls() -> type[ProjectContext]:
    """Return `yggdrasil_agents.ProjectContext` if available, else local class."""
    try:
        mod = importlib.import_module("yggdrasil_agents")
        cls = getattr(mod, "ProjectContext", None)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            return cast("type[ProjectContext]", cls)
    except ImportError:
        pass
    return ProjectContext


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with microsecond precision."""
    return datetime.now(UTC).isoformat()


class Project(BaseModel):
    """Stored project record (`projects` table in `studio.db`)."""

    id: str
    name: str
    instructions: str = ""
    air_gapped: bool = False
    created_at: str
    updated_at: str


class ProjectNote(BaseModel):
    """Pinned project note (`project_notes` table in `studio.db`)."""

    id: str
    project_id: str
    title: str
    content: str
    created_at: str


class Conversation(BaseModel):
    """Stored conversation thread (`conversations` table in `studio.db`)."""

    id: str
    project_id: str | None = None
    title: str
    pinned: bool = False
    created_at: str
    updated_at: str


class StoredMessage(BaseModel):
    """Stored message inside a conversation (`messages` table in `studio.db`)."""

    id: str
    conversation_id: str
    role: ChatRole
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class Gem(BaseModel):
    """Reusable specialist persona (`gems` table in `studio.db`, `SPEC-005`)."""

    id: str
    name: str
    icon: str = "💎"
    description: str = ""
    instructions: str
    default_mode: GemMode = "chat"
    created_at: str


class CanvasArtifact(BaseModel):
    """Saved Canvas document, code file, HTML view, or Deep Research report (`artifacts` table)."""

    id: str
    conversation_id: str | None = None
    project_id: str | None = None
    title: str
    kind: ArtifactKind = "markdown"
    content: str
    created_at: str
    updated_at: str


_MAX_NOTE_EXCERPT_CHARS = 2000

_DEFAULT_GEMS: tuple[tuple[str, str, str, str, GemMode], ...] = (
    (
        "ChemEng Process Architect",
        "⚗️",
        "Mass/energy balances, thermodynamics, reactor & separation design.",
        (
            "Prioritize rigorous mass/energy balances, SI units, Peng-Robinson/NRTL "
            "thermodynamics, and explicit process engineering assumptions."
        ),
        "canvas",
    ),
    (
        "Python AST & Code Optimizer",
        "🐍",
        "Static AST complexity analysis, Pydantic typing, and vectorization.",
        (
            "Inspect Python code via deterministic AST analysis, enforce strict Pydantic "
            "BaseModel contracts, and eliminate O(n^2) loops."
        ),
        "canvas",
    ),
    (
        "PID & Control Loop Tuner",
        "🎛️",
        "SIMC/IMC PID tuning, step-response stability, and damping analysis.",
        (
            "Formulate FOPDT/SOPDT transfer functions, compute SIMC/IMC Kp, Ki, Kd gains, "
            "and verify closed-loop overshoot and settling time."
        ),
        "thinking",
    ),
    (
        "Deep Research & Theory Verifier",
        "🔬",
        "Multi-step literature synthesis, citation cross-check, and gap analysis.",
        (
            "Decompose research questions into an explicit investigation plan, cross-check "
            "against verified local references, and output a cited report."
        ),
        "deep_research",
    ),
)


class StudioStore:
    """Thread-safe SQLite store backing Yggdrasil Studio Projects & Conversations."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._init_schema()

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self._db_path

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        self._conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                instructions TEXT NOT NULL DEFAULT '',
                air_gapped INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_notes (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                project_id TEXT NULL REFERENCES projects(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gems (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT '💎',
                description TEXT NOT NULL DEFAULT '',
                instructions TEXT NOT NULL DEFAULT '',
                default_mode TEXT NOT NULL DEFAULT 'chat',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NULL REFERENCES conversations(id) ON DELETE SET NULL,
                project_id TEXT NULL REFERENCES projects(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'markdown',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_project_notes_project
                ON project_notes(project_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_conversations_project_updated
                ON conversations(project_id, pinned DESC, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                ON messages(conversation_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_artifacts_project_updated
                ON artifacts(project_id, updated_at DESC);
            """
        )

    def seed_defaults_if_empty(self) -> Project | None:
        """Seed default Chemical Engineering project and the 4 built-in Gems if empty."""
        with self._lock:
            gem_row = self._conn.execute("SELECT COUNT(*) AS cnt FROM gems").fetchone()
            gem_count = int(gem_row["cnt"]) if gem_row is not None else 0
            if gem_count == 0:
                for g_name, g_icon, g_desc, g_inst, g_mode in _DEFAULT_GEMS:
                    self.create_gem(
                        name=g_name,
                        instructions=g_inst,
                        icon=g_icon,
                        description=g_desc,
                        default_mode=g_mode,
                    )

            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM projects").fetchone()
            count = int(row["cnt"]) if row is not None else 0
            if count > 0:
                return None
            return self.create_project(
                name="Chemical Engineering",
                instructions=(
                    "Focus on rigorous mass/energy balances, SI units, and process control."
                ),
                air_gapped=False,
            )

    # ------------------------------------------------------------------
    # Projects & Notes
    # ------------------------------------------------------------------

    def create_project(
        self,
        name: str,
        instructions: str = "",
        air_gapped: bool = False,
    ) -> Project:
        """Create and persist a new Project."""
        clean_name = name.strip() or "Untitled project"
        now = _utc_now_iso()
        project = Project(
            id=uuid.uuid4().hex,
            name=clean_name,
            instructions=instructions,
            air_gapped=bool(air_gapped),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO projects (id, name, instructions, air_gapped, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project.id,
                    project.name,
                    project.instructions,
                    1 if project.air_gapped else 0,
                    project.created_at,
                    project.updated_at,
                ),
            )
        return project

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        instructions: str | None = None,
        air_gapped: bool | None = None,
    ) -> Project:
        """Update an existing Project's fields and touch `updated_at`."""
        with self._lock:
            existing = self.get_project(project_id)
            if existing is None:
                raise KeyError(f"Project not found: {project_id}")

            new_name = (name.strip() or existing.name) if name is not None else existing.name
            new_instructions = (
                instructions if instructions is not None else existing.instructions
            )
            new_air_gapped = (
                bool(air_gapped) if air_gapped is not None else existing.air_gapped
            )
            now = _utc_now_iso()

            self._conn.execute(
                """
                UPDATE projects
                SET name = ?, instructions = ?, air_gapped = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_name,
                    new_instructions,
                    1 if new_air_gapped else 0,
                    now,
                    project_id,
                ),
            )
            return Project(
                id=existing.id,
                name=new_name,
                instructions=new_instructions,
                air_gapped=new_air_gapped,
                created_at=existing.created_at,
                updated_at=now,
            )

    def delete_project(self, project_id: str) -> None:
        """Delete a project, moving its conversations/artifacts to `project_id = None` and deleting notes."""
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute(
                "UPDATE conversations SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )
            self._conn.execute(
                "UPDATE artifacts SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )
            self._conn.execute(
                "DELETE FROM project_notes WHERE project_id = ?",
                (project_id,),
            )
            self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def list_projects(self) -> list[Project]:
        """List all projects ordered by most recently updated first."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, name, instructions, air_gapped, created_at, updated_at
                FROM projects
                ORDER BY updated_at DESC, rowid DESC
                """
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def get_project(self, project_id: str) -> Project | None:
        """Retrieve a single project by ID, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, name, instructions, air_gapped, created_at, updated_at
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
        return self._row_to_project(row) if row is not None else None

    def add_note(self, project_id: str, title: str, content: str) -> ProjectNote:
        """Add a pinned note to a project and touch the project's `updated_at`."""
        now = _utc_now_iso()
        clean_title = title.strip() or "Note"
        note = ProjectNote(
            id=uuid.uuid4().hex,
            project_id=project_id,
            title=clean_title,
            content=content,
            created_at=now,
        )
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute(
                """
                INSERT INTO project_notes (id, project_id, title, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (note.id, note.project_id, note.title, note.content, note.created_at),
            )
            self._conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return note

    def list_notes(self, project_id: str) -> list[ProjectNote]:
        """Return all notes for a project in chronological order."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, project_id, title, content, created_at
                FROM project_notes
                WHERE project_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (project_id,),
            ).fetchall()
        return [
            ProjectNote(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                title=str(row["title"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def delete_note(self, note_id: str) -> None:
        """Delete a single project note by ID."""
        with self._lock:
            self._conn.execute("DELETE FROM project_notes WHERE id = ?", (note_id,))

    def build_project_context(self, project_id: str | None) -> ProjectContext | None:
        """Construct a `ProjectContext` with trimmed pinned notes for the chat pipeline."""
        if not project_id:
            return None
        project = self.get_project(project_id)
        if project is None:
            return None
        notes = self.list_notes(project_id)
        formatted_notes: list[str] = []
        for note in notes:
            body = note.content.strip()
            combined = f"{note.title}: {body}" if note.title else body
            if len(combined) > _MAX_NOTE_EXCERPT_CHARS:
                combined = combined[: _MAX_NOTE_EXCERPT_CHARS - 1].rstrip() + "…"
            if combined:
                formatted_notes.append(combined)

        ctx_cls = _resolve_project_context_cls()
        result: ProjectContext = ctx_cls(
            project_id=project.id,
            name=project.name,
            instructions=project.instructions,
            pinned_notes=formatted_notes,
            air_gapped=project.air_gapped,
        )
        return result

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def create_conversation(
        self,
        project_id: str | None = None,
        title: str = "New chat",
    ) -> Conversation:
        """Create and persist a new Conversation."""
        clean_title = title.strip() or "New chat"
        now = _utc_now_iso()
        conv = Conversation(
            id=uuid.uuid4().hex,
            project_id=project_id,
            title=clean_title,
            pinned=False,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute(
                """
                INSERT INTO conversations (id, project_id, title, pinned, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    conv.id,
                    conv.project_id,
                    conv.title,
                    0,
                    conv.created_at,
                    conv.updated_at,
                ),
            )
        return conv

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        """Rename a conversation and touch its `updated_at` timestamp."""
        clean_title = title.strip() or "New chat"
        now = _utc_now_iso()
        with self._lock:
            self._conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (clean_title, now, conversation_id),
            )

    def set_pinned(self, conversation_id: str, pinned: bool) -> None:
        """Pin or unpin a conversation."""
        with self._lock:
            self._conn.execute(
                "UPDATE conversations SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, conversation_id),
            )

    def move_conversation(self, conversation_id: str, project_id: str | None) -> None:
        """Move a conversation into a project (or `None` for no project)."""
        now = _utc_now_iso()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute(
                "UPDATE conversations SET project_id = ?, updated_at = ? WHERE id = ?",
                (project_id, now, conversation_id),
            )

    def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation, unlinking saved artifacts and cascade-deleting messages."""
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute(
                "UPDATE artifacts SET conversation_id = NULL WHERE conversation_id = ?",
                (conversation_id,),
            )
            self._conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            self._conn.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Retrieve a single conversation by ID, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, project_id, title, pinned, created_at, updated_at
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return self._row_to_conversation(row) if row is not None else None

    def list_conversations(
        self,
        project_id: str | None = None,
        *,
        all_projects: bool = True,
        search: str = "",
    ) -> list[Conversation]:
        """List conversations ordered by `pinned DESC, updated_at DESC`.

        - If `project_id` is given, filters to that project.
        - If `project_id is None` and `all_projects is False`, filters to conversations
          with `project_id IS NULL`.
        - If `search` is non-empty, matches conversation title or any message content.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if project_id is not None:
            clauses.append("c.project_id = ?")
            params.append(project_id)
        elif not all_projects:
            clauses.append("c.project_id IS NULL")

        query = search.strip()
        if query:
            like_pattern = f"%{query.lower()}%"
            clauses.append(
                "("
                "LOWER(c.title) LIKE ? "
                "OR EXISTS ("
                "SELECT 1 FROM messages m "
                "WHERE m.conversation_id = c.id AND LOWER(m.content) LIKE ?"
                ")"
                ")"
            )
            params.extend([like_pattern, like_pattern])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT c.id, c.project_id, c.title, c.pinned, c.created_at, c.updated_at
            FROM conversations c
            {where_sql}
            ORDER BY c.pinned DESC, c.updated_at DESC, c.rowid DESC
        """
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_conversation(row) for row in rows]

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        role: ChatRole,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> StoredMessage:
        """Append a message to a conversation and update the conversation's `updated_at`."""
        now = _utc_now_iso()
        meta_dict: dict[str, Any] = dict(meta) if meta is not None else {}
        msg = StoredMessage(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            role=role,
            content=content,
            meta=meta_dict,
            created_at=now,
        )
        meta_json = json.dumps(meta_dict, ensure_ascii=False)
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.id,
                    msg.conversation_id,
                    msg.role,
                    msg.content,
                    meta_json,
                    msg.created_at,
                ),
            )
            self._conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return msg

    def list_messages(self, conversation_id: str) -> list[StoredMessage]:
        """Return all messages in a conversation ordered chronologically."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, conversation_id, role, content, meta_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def history_for_pipeline(
        self,
        conversation_id: str,
        limit: int = 12,
    ) -> list[ChatHistoryMessage]:
        """Return the last `limit` messages formatted as `ChatHistoryMessage` objects."""
        if limit <= 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT role, content
                FROM (
                    SELECT role, content, created_at, rowid
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id, limit),
            ).fetchall()

        msg_cls = _resolve_chat_history_cls()
        history: list[ChatHistoryMessage] = []
        for row in rows:
            raw_role = str(row["role"])
            role: ChatRole = (
                raw_role  # type: ignore[assignment]
                if raw_role in ("user", "assistant", "system")
                else "user"
            )
            item: ChatHistoryMessage = msg_cls(role=role, content=str(row["content"]))
            history.append(item)
        return history

    # ------------------------------------------------------------------
    # Gems (SPEC-005)
    # ------------------------------------------------------------------

    def create_gem(
        self,
        name: str,
        instructions: str,
        *,
        icon: str = "💎",
        description: str = "",
        default_mode: GemMode = "chat",
    ) -> Gem:
        """Create and persist a reusable specialist Gem persona."""
        clean_name = name.strip() or "Custom Gem"
        clean_icon = icon.strip() or "💎"
        now = _utc_now_iso()
        gem = Gem(
            id=uuid.uuid4().hex,
            name=clean_name,
            icon=clean_icon,
            description=description.strip(),
            instructions=instructions,
            default_mode=default_mode,
            created_at=now,
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gems (id, name, icon, description, instructions, default_mode, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gem.id,
                    gem.name,
                    gem.icon,
                    gem.description,
                    gem.instructions,
                    gem.default_mode,
                    gem.created_at,
                ),
            )
        return gem

    def list_gems(self) -> list[Gem]:
        """List all Gems ordered by creation time ascending."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, name, icon, description, instructions, default_mode, created_at
                FROM gems
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        return [self._row_to_gem(row) for row in rows]

    def get_gem(self, gem_id: str) -> Gem | None:
        """Retrieve a single Gem by ID, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, name, icon, description, instructions, default_mode, created_at
                FROM gems
                WHERE id = ?
                """,
                (gem_id,),
            ).fetchone()
        return self._row_to_gem(row) if row is not None else None

    def delete_gem(self, gem_id: str) -> None:
        """Delete a Gem by ID."""
        with self._lock:
            self._conn.execute("DELETE FROM gems WHERE id = ?", (gem_id,))

    # ------------------------------------------------------------------
    # Canvas Artifacts / Library (SPEC-005)
    # ------------------------------------------------------------------

    def save_artifact(
        self,
        title: str,
        content: str,
        *,
        kind: ArtifactKind = "markdown",
        conversation_id: str | None = None,
        project_id: str | None = None,
    ) -> CanvasArtifact:
        """Save a Canvas artifact or Deep Research report into the persistent Library."""
        clean_title = title.strip() or "Untitled Artifact"
        now = _utc_now_iso()
        artifact = CanvasArtifact(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            project_id=project_id,
            title=clean_title,
            kind=kind,
            content=content,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute(
                """
                INSERT INTO artifacts (
                    id, conversation_id, project_id, title, kind, content, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.conversation_id,
                    artifact.project_id,
                    artifact.title,
                    artifact.kind,
                    artifact.content,
                    artifact.created_at,
                    artifact.updated_at,
                ),
            )
        return artifact

    def update_artifact(
        self,
        artifact_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        kind: ArtifactKind | None = None,
    ) -> CanvasArtifact:
        """Update an existing Canvas artifact's title, content, or kind."""
        with self._lock:
            existing = self.get_artifact(artifact_id)
            if existing is None:
                raise KeyError(f"Artifact not found: {artifact_id}")

            new_title = (title.strip() or existing.title) if title is not None else existing.title
            new_content = content if content is not None else existing.content
            new_kind: ArtifactKind = kind if kind is not None else existing.kind
            now = _utc_now_iso()

            self._conn.execute(
                """
                UPDATE artifacts
                SET title = ?, kind = ?, content = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_title, new_kind, new_content, now, artifact_id),
            )
            return CanvasArtifact(
                id=existing.id,
                conversation_id=existing.conversation_id,
                project_id=existing.project_id,
                title=new_title,
                kind=new_kind,
                content=new_content,
                created_at=existing.created_at,
                updated_at=now,
            )

    def list_artifacts(
        self,
        project_id: str | None = None,
        search: str = "",
    ) -> list[CanvasArtifact]:
        """List saved Canvas artifacts ordered by `updated_at DESC`."""
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        query = search.strip()
        if query:
            like_pattern = f"%{query.lower()}%"
            clauses.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ?)")
            params.extend([like_pattern, like_pattern])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT id, conversation_id, project_id, title, kind, content, created_at, updated_at
            FROM artifacts
            {where_sql}
            ORDER BY updated_at DESC, rowid DESC
        """
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def get_artifact(self, artifact_id: str) -> CanvasArtifact | None:
        """Retrieve a single Canvas artifact by ID, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, conversation_id, project_id, title, kind, content, created_at, updated_at
                FROM artifacts
                WHERE id = ?
                """,
                (artifact_id,),
            ).fetchone()
        return self._row_to_artifact(row) if row is not None else None

    def delete_artifact(self, artifact_id: str) -> None:
        """Delete a Canvas artifact by ID."""
        with self._lock:
            self._conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))

    # ------------------------------------------------------------------
    # Row Mappers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_gem(row: sqlite3.Row) -> Gem:
        raw_mode = str(row["default_mode"])
        mode: GemMode = (
            raw_mode  # type: ignore[assignment]
            if raw_mode in ("chat", "canvas", "deep_research", "thinking")
            else "chat"
        )
        return Gem(
            id=str(row["id"]),
            name=str(row["name"]),
            icon=str(row["icon"]),
            description=str(row["description"]),
            instructions=str(row["instructions"]),
            default_mode=mode,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> CanvasArtifact:
        raw_conv = row["conversation_id"]
        raw_proj = row["project_id"]
        raw_kind = str(row["kind"])
        kind: ArtifactKind = (
            raw_kind  # type: ignore[assignment]
            if raw_kind in ("markdown", "code", "html", "report")
            else "markdown"
        )
        return CanvasArtifact(
            id=str(row["id"]),
            conversation_id=str(raw_conv) if raw_conv is not None else None,
            project_id=str(raw_proj) if raw_proj is not None else None,
            title=str(row["title"]),
            kind=kind,
            content=str(row["content"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=str(row["id"]),
            name=str(row["name"]),
            instructions=str(row["instructions"]),
            air_gapped=bool(int(row["air_gapped"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> Conversation:
        raw_project = row["project_id"]
        return Conversation(
            id=str(row["id"]),
            project_id=str(raw_project) if raw_project is not None else None,
            title=str(row["title"]),
            pinned=bool(int(row["pinned"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> StoredMessage:
        raw_meta = str(row["meta_json"] or "{}")
        try:
            parsed_meta = json.loads(raw_meta)
            meta_dict = parsed_meta if isinstance(parsed_meta, dict) else {}
        except ValueError:
            meta_dict = {}
        raw_role = str(row["role"])
        role: ChatRole = (
            raw_role  # type: ignore[assignment]
            if raw_role in ("user", "assistant", "system")
            else "user"
        )
        return StoredMessage(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            role=role,
            content=str(row["content"]),
            meta=meta_dict,
            created_at=str(row["created_at"]),
        )
