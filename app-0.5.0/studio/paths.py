"""Runtime path resolution for Yggdrasil Studio (Standalone Version 4 & Monorepo)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

StudioMode = Literal["standalone", "monorepo"]


@dataclass(frozen=True)
class StudioPaths:
    """Resolved filesystem paths for Yggdrasil Studio in standalone or monorepo mode."""

    mode: StudioMode
    root_dir: Path
    app_dir: Path
    agents_dir: Path
    vaults_dir: Path
    studio_db: Path
    personal_vault_db: Path
    state_tree_db: Path
    references_json: Path
    user_content_dir: Path
    logs_dir: Path
    changelog_dir: Path
    specs_dir: Path
    resources_dir: Path
    settings_json: Path

    @property
    def markdowns_dir(self) -> Path:
        """Backward-compatible alias for specs_dir."""
        return self.specs_dir


def resolve_studio_paths(anchor: Path | None = None) -> StudioPaths:
    """Resolve standalone Version 4 layout vs monorepo layout."""
    start = (anchor or Path(__file__)).resolve()
    start_dir = start.parent if start.is_file() else start

    candidates: list[Path] = [
        start_dir,
        start_dir.parent,
        start_dir.parent.parent,
    ]
    for base in candidates:
        if (base / "agents_and_lms" / "yggdrasil_agents").is_dir():
            app_v5 = base / "app-0.5.0"
            app_v4 = base / "app-0.4.0"
            if app_v5.is_dir():
                app_dir = app_v5
            elif app_v4.is_dir():
                app_dir = app_v4
            elif start_dir.name == "studio":
                app_dir = start_dir.parent
            else:
                app_dir = base

            vaults_dir = base / "data_and_vaults"
            user_content_dir = base / "user_content"
            return StudioPaths(
                mode="standalone",
                root_dir=base,
                app_dir=app_dir,
                agents_dir=base / "agents_and_lms",
                vaults_dir=vaults_dir,
                studio_db=vaults_dir / "studio.db",
                personal_vault_db=vaults_dir / "personal_vault.db",
                state_tree_db=vaults_dir / "state_tree.db",
                references_json=vaults_dir / "references.json",
                user_content_dir=user_content_dir,
                logs_dir=base / "logs",
                changelog_dir=base / "Changelog",
                specs_dir=base / "markdowns_and_specs",
                resources_dir=base / "resources",
                settings_json=user_content_dir / "studio_settings.json",
            )

    app_dir = start_dir.parent if start_dir.name == "studio" else start_dir
    root_dir = app_dir.parent
    vaults_dir = app_dir / "vaults"
    user_content_dir = app_dir / "user_content"
    return StudioPaths(
        mode="monorepo",
        root_dir=root_dir,
        app_dir=app_dir,
        agents_dir=root_dir / "03-agent-foundry",
        vaults_dir=vaults_dir,
        studio_db=vaults_dir / "studio.db",
        personal_vault_db=vaults_dir / "personal_vault.db",
        state_tree_db=vaults_dir / "state_tree.db",
        references_json=vaults_dir / "references.json",
        user_content_dir=user_content_dir,
        logs_dir=app_dir / "logs",
        changelog_dir=root_dir / "Changelog",
        specs_dir=root_dir / "02-yggdrasil-lab" / "specs",
        resources_dir=app_dir / "resources",
        settings_json=user_content_dir / "studio_settings.json",
    )


def ensure_studio_directories(paths: StudioPaths) -> None:
    """Create local vaults, user_content subtrees, logs, resources, and changelog folders."""
    for sub in ("brain", "instructions", "exports", "workspaces"):
        (paths.user_content_dir / sub).mkdir(parents=True, exist_ok=True)
    for folder in (
        paths.vaults_dir,
        paths.user_content_dir,
        paths.logs_dir,
        paths.resources_dir,
        paths.changelog_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    if not paths.references_json.exists():
        paths.references_json.write_text(
            json.dumps({"references": []}, indent=2),
            encoding="utf-8",
        )


def ensure_agents_on_path(paths: StudioPaths) -> None:
    """Ensure both `agents_dir` and `app_dir` are importable on `sys.path`."""
    for target in (paths.app_dir, paths.agents_dir):
        target_str = str(target)
        if target_str not in sys.path:
            sys.path.insert(0, target_str)
