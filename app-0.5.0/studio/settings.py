"""User settings and API key discovery for Yggdrasil Studio (SPEC-004)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from studio.paths import StudioPaths, resolve_studio_paths


class StudioSettings(BaseModel):
    """Persisted local settings for Yggdrasil Studio (never stores API keys)."""

    model_config = ConfigDict(extra="ignore")

    default_model: str = "auto"
    local_only: bool = False
    sidebar_collapsed: bool = False
    window_geometry: str | None = None
    last_conversation_id: str | None = None
    last_project_id: str | None = None


def load_settings(path: Path) -> StudioSettings:
    """Load `StudioSettings` from JSON on disk, returning defaults if missing or corrupt."""
    if not path.is_file():
        return StudioSettings()
    try:
        raw = path.read_text(encoding="utf-8")
        return StudioSettings.model_validate_json(raw)
    except (OSError, ValidationError, ValueError):
        return StudioSettings()


def save_settings(settings: StudioSettings, path: Path) -> None:
    """Persist `StudioSettings` atomically to JSON on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.model_dump_json(indent=2)
    path.write_text(payload, encoding="utf-8")


def _parse_env_file_for_key(env_path: Path) -> str | None:
    """Read `.env` file and extract `GEMINI_API_KEY` or `GOOGLE_API_KEY` if present."""
    if not env_path.is_file():
        return None
    try:
        lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key_name = key.strip()
        if key_name not in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
            cleaned = cleaned[1:-1].strip()
        if cleaned:
            return cleaned
    return None


def load_gemini_api_key(paths: StudioPaths | None = None) -> str | None:
    """Check process environment and local `.env` files for a Gemini API key."""
    for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val

    resolved = paths or resolve_studio_paths()
    for candidate in (resolved.app_dir / ".env", resolved.root_dir / ".env"):
        found = _parse_env_file_for_key(candidate)
        if found:
            return found
    return None
