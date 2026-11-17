"""Yggdrasil Master Application Entrypoint.

Imports `yggdrasil_agents`, initializes the local SQLite vaults (`personal_vault.db`
and `state_tree.db`) alongside `references.json`, and renders the animated SVG tree UI.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
_STANDALONE_AGENTS = APP_DIR.parent / "agents_and_lms"
FOUNDRY_DIR = (
    _STANDALONE_AGENTS
    if (_STANDALONE_AGENTS / "yggdrasil_agents").is_dir()
    else APP_DIR.parent / "03-agent-foundry"
)
for _candidate in (str(APP_DIR), str(FOUNDRY_DIR)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from exported_nano_agents import (
    get_exported_nano_manifest,
    load_reference_entries,
)

from yggdrasil_agents import (
    ContextNodeState,
    LeavesCloudAgent,
    LocalEngine,
    LocalEngineConfig,
    NestedModelOrchestrator,
    OrchestratorConfig,
    RootsAgent,
    TrunkRouter,
    TwigsExecutor,
)

_STANDALONE_VAULTS = APP_DIR.parent / "data_and_vaults"
VAULTS_DIR = _STANDALONE_VAULTS if _STANDALONE_VAULTS.is_dir() else APP_DIR / "vaults"
PERSONAL_VAULT_DB = Path(os.getenv("PERSONAL_VAULT_DB_PATH", VAULTS_DIR / "personal_vault.db"))
STATE_TREE_DB = Path(os.getenv("STATE_TREE_DB_PATH", VAULTS_DIR / "state_tree.db"))
REFERENCES_JSON = Path(os.getenv("REFERENCES_JSON_PATH", VAULTS_DIR / "references.json"))


def init_personal_vault(db_path: Path = PERSONAL_VAULT_DB) -> None:
    """Initialize the strictly air-gapped local personal_vault.db SQLite schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS personal_notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                privacy_tier TEXT NOT NULL DEFAULT 'air_gapped'
                    CHECK (privacy_tier = 'air_gapped'),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def init_state_tree_db(db_path: Path = STATE_TREE_DB) -> None:
    """Initialize state_tree.db storing Yggdrasil node topology and W_i decay state."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tree_nodes (
                node_id TEXT PRIMARY KEY,
                parent_id TEXT,
                label TEXT NOT NULL,
                tier TEXT NOT NULL CHECK (tier IN ('roots', 'trunk', 'twigs', 'leaves')),
                initial_weight REAL NOT NULL DEFAULT 1.0,
                decay_rate REAL NOT NULL DEFAULT 0.05,
                resonance_count INTEGER NOT NULL DEFAULT 0,
                current_weight REAL NOT NULL DEFAULT 1.0,
                contains_personal_vault_data INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def load_references(json_path: Path = REFERENCES_JSON) -> dict[str, Any]:
    """Load non-sensitive scientific and technical references from vaults/references.json."""
    if not json_path.exists():
        return {"schema_version": "1.0", "references": []}
    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {json_path}")
    return data


def render_yggdrasil_svg_tree(
    nodes: list[ContextNodeState],
    router: TrunkRouter | None = None,
) -> str:
    """Render an animated Yggdrasil SVG tree reflecting W_i weights and privacy tiers."""
    active_router = router or TrunkRouter()
    width, height = 800, 520
    center_x, trunk_base_y = width // 2, 460

    svg_elements: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            'width="100%" height="100%" role="img" aria-label="Yggdrasil Context Tree">'
        ),
        "<defs>",
        '<radialGradient id="yggdrasilGlow" cx="50%" cy="50%" r="50%">',
        '<stop offset="0%" stop-color="#1e293b"/>',
        '<stop offset="100%" stop-color="#090d16"/>',
        "</radialGradient>",
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="url(#yggdrasilGlow)"/>',
        (
            f'<line x1="{center_x}" y1="{trunk_base_y}" x2="{center_x}" y2="170" '
            'stroke="#8b5cf6" stroke-width="10" stroke-linecap="round"/>'
        ),
    ]

    total = max(len(nodes), 1)
    for idx, node in enumerate(nodes):
        decision = active_router.evaluate_node(node, allow_cloud=not node.contains_personal_vault_data)
        radius = max(10.0, min(32.0, 12.0 + decision.weight * 10.0))
        opacity = max(0.25, min(1.0, 0.35 + decision.weight * 0.5))
        fill = "#10b981" if decision.air_gap_blocked else "#38bdf8"

        spread = (idx - (total - 1) / 2.0) * 140.0
        node_x = center_x + spread
        node_y = 380.0 if decision.air_gap_blocked else 130.0
        anchor_y = trunk_base_y - 60 if decision.air_gap_blocked else 185

        label = html.escape(node.label)
        svg_elements.append(
            f'<line x1="{center_x}" y1="{anchor_y}" x2="{node_x:.1f}" y2="{node_y:.1f}" '
            f'stroke="{fill}" stroke-opacity="{opacity:.2f}" stroke-width="3"/>'
        )
        svg_elements.append(
            f'<circle cx="{node_x:.1f}" cy="{node_y:.1f}" r="{radius:.1f}" '
            f'fill="{fill}" fill-opacity="{opacity:.2f}">'
            '<animate attributeName="r" '
            f'values="{radius:.1f};{radius + 2.5:.1f};{radius:.1f}" '
            'dur="3.5s" repeatCount="indefinite"/>'
            "</circle>"
        )
        svg_elements.append(
            f'<text x="{node_x:.1f}" y="{node_y + radius + 16:.1f}" '
            'fill="#e2e8f0" font-family="sans-serif" font-size="12" text-anchor="middle">'
            f"{label} (W={decision.weight:.2f})</text>"
        )

    svg_elements.append("</svg>")
    return "\n".join(svg_elements)


async def bootstrap_app() -> dict[str, Any]:
    """Initialize local vaults, shared resident engine, and render initial tree preview."""
    await asyncio.to_thread(init_personal_vault)
    await asyncio.to_thread(init_state_tree_db)
    references = await asyncio.to_thread(load_references)
    ref_entries = await asyncio.to_thread(load_reference_entries, REFERENCES_JSON)

    provider = os.getenv("YGGDRASIL_LOCAL_PROVIDER", "ollama")
    model_name = os.getenv("YGGDRASIL_LOCAL_MODEL", "yggdrasil-nano")
    config = LocalEngineConfig(
        provider="lm_studio" if provider == "lm_studio" else "ollama",
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        lm_studio_base_url=os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
        model_name=model_name,
    )
    engine = LocalEngine.get_shared(config)
    roots = RootsAgent(engine=engine)
    trunk = TrunkRouter(engine=engine)
    twigs = TwigsExecutor(engine=engine)
    leaves = LeavesCloudAgent(model_name=os.getenv("YGGDRASIL_CLOUD_MODEL", "gemini-2.5-flash"))
    orchestrator = NestedModelOrchestrator(
        config=OrchestratorConfig(
            nano_model_name=model_name,
            references_json_path=str(REFERENCES_JSON),
        ),
        engine=engine,
        trunk_router=trunk,
        twigs_executor=twigs,
        leaves_agent=leaves,
    )

    sample_prompt = (
        "#CALC_SOLVE: Reynolds Check mode=reynolds_number density=998.2 velocity=1.5 "
        "diameter=0.05 viscosity=0.001002\n"
        "reynolds_number\n"
        "[/#CALC_SOLVE]\n"
        "#CONTROL_SYSTEM: CSTR IMC PID\n"
        "kp=2.0 tau=10.0 theta=2.0 controller_type=PID tuning_method=imc imc_tau_c=2.0\n"
        "[/#CONTROL_SYSTEM]\n"
        "#RESEARCH_GAP: IMC Literature Lookup\n"
        "Internal model control for FOPDT chemical process tuning.\n"
        "[/#RESEARCH_GAP]"
    )
    nano_report = await orchestrator.process_prompt(
        sample_prompt,
        source_id="bootstrap_check",
        from_personal_vault=False,
        local_references=ref_entries,
    )

    sample_nodes = [
        ContextNodeState(
            node_id="root-personal-1",
            label="Personal Vault Root",
            initial_weight=1.0,
            elapsed_hours=2.0,
            resonance_count=1,
            contains_personal_vault_data=True,
        ),
        ContextNodeState(
            node_id="leaf-chemeng-1",
            label="ChemEng Kinetics Leaf",
            initial_weight=0.9,
            elapsed_hours=1.0,
            resonance_count=2,
            contains_personal_vault_data=False,
            summary="Reaction kinetics literature synthesis",
        ),
    ]
    svg_preview = render_yggdrasil_svg_tree(sample_nodes, router=trunk)
    engine_status = await engine.healthcheck()
    await LocalEngine.reset_shared()

    return {
        "engine_status": engine_status.model_dump(),
        "references_count": len(references.get("references", [])),
        "nano_manifest_count": len(get_exported_nano_manifest()),
        "agents_wired": {
            "roots": type(roots).__name__,
            "trunk": type(trunk).__name__,
            "twigs": type(twigs).__name__,
            "leaves": type(leaves).__name__,
            "orchestrator": type(orchestrator).__name__,
        },
        "deterministic_benchmark": {
            "total_slices": nano_report.total_slices,
            "deterministic_hits": nano_report.deterministic_hits,
            "nano_llm_calls": nano_report.nano_llm_calls,
            "token_savings_ratio": round(nano_report.token_savings_ratio, 4),
            "total_latency_ms": round(nano_report.total_latency_ms, 3),
        },
        "svg_bytes": len(svg_preview.encode()),
    }


if __name__ == "__main__":
    summary = asyncio.run(bootstrap_app())
    print(json.dumps(summary, indent=2))
