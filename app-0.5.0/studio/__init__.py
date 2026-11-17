"""Yggdrasil Studio v0.5.0 package (storage, paths, settings, and PySide6 GUI)."""

from __future__ import annotations

from studio.paths import (
    StudioMode,
    StudioPaths,
    ensure_agents_on_path,
    ensure_studio_directories,
    resolve_studio_paths,
)
from studio.settings import (
    StudioSettings,
    load_gemini_api_key,
    load_settings,
    save_settings,
)
from studio.store import (
    ArtifactKind,
    CanvasArtifact,
    Conversation,
    Gem,
    GemMode,
    Project,
    ProjectNote,
    StoredMessage,
    StudioStore,
)

__version__ = "0.5.0"

__all__ = [
    "ArtifactKind",
    "CanvasArtifact",
    "Conversation",
    "Gem",
    "GemMode",
    "Project",
    "ProjectNote",
    "StoredMessage",
    "StudioMode",
    "StudioPaths",
    "StudioSettings",
    "StudioStore",
    "__version__",
    "ensure_agents_on_path",
    "ensure_studio_directories",
    "load_gemini_api_key",
    "load_settings",
    "resolve_studio_paths",
    "save_settings",
]
