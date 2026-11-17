"""Yggdrasil Sovereign AI Studio — Self-Sufficient Gemini-Branded Central GUI & CLI.

Runs identically inside `c:\\AntiGravityFiles\\MasterAgent\\04-yggdrasil-app\\` AND inside any
self-contained `output\\Version X\\executables\\` package without relying on external CDNs
or hard-coded source workspace paths.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class StudioPaths:
    """Resolved runtime paths supporting both monorepo and standalone output distributions."""

    mode: str
    root_dir: Path
    agents_dir: Path
    vaults_dir: Path
    changelog_dir: Path
    markdowns_dir: Path
    user_content_dir: Path
    personal_vault_db: Path
    state_tree_db: Path
    references_json: Path


def resolve_studio_paths() -> StudioPaths:
    """Detect whether running from a standalone `output/Version X` bundle or the monorepo."""
    script_dir = Path(__file__).resolve().parent
    standalone_root = script_dir.parent
    if (standalone_root / "agents_and_lms" / "yggdrasil_agents").is_dir():
        vaults_dir = standalone_root / "data_and_vaults"
        return StudioPaths(
            mode="standalone",
            root_dir=standalone_root,
            agents_dir=standalone_root / "agents_and_lms",
            vaults_dir=vaults_dir,
            changelog_dir=standalone_root / "Changelog",
            markdowns_dir=standalone_root / "markdowns_and_specs",
            user_content_dir=standalone_root / "user_content",
            personal_vault_db=vaults_dir / "personal_vault.db",
            state_tree_db=vaults_dir / "state_tree.db",
            references_json=vaults_dir / "references.json",
        )

    repo_root = script_dir.parent
    vaults_dir = script_dir / "vaults"
    return StudioPaths(
        mode="monorepo",
        root_dir=repo_root,
        agents_dir=repo_root / "03-agent-foundry",
        vaults_dir=vaults_dir,
        changelog_dir=repo_root / "Changelog",
        markdowns_dir=repo_root / "02-yggdrasil-lab" / "specs",
        user_content_dir=script_dir / "user_content",
        personal_vault_db=vaults_dir / "personal_vault.db",
        state_tree_db=vaults_dir / "state_tree.db",
        references_json=vaults_dir / "references.json",
    )


PATHS = resolve_studio_paths()
if str(PATHS.agents_dir) not in sys.path:
    sys.path.insert(0, str(PATHS.agents_dir))

from yggdrasil_agents import (
    ContextNodeState,
    LocalEngine,
    LocalEngineConfig,
    NestedModelOrchestrator,
    OrchestratorConfig,
    ReferenceEntry,
    TrunkRouter,
    UiAgentInput,
    UiThemeSpec,
    UserInterfaceNestedAgent,
    pre_group_prompt,
)
from yggdrasil_agents.nano_models import (
    DEFAULT_MICRO_WEIGHTS_1024,
)


def ensure_runtime_directories(paths: StudioPaths = PATHS) -> None:
    """Create user_content (Antigravity/Gemini-style hierarchy), vaults, and databases."""
    for sub in ("brain", "instructions", "exports", "workspaces"):
        (paths.user_content_dir / sub).mkdir(parents=True, exist_ok=True)
    paths.vaults_dir.mkdir(parents=True, exist_ok=True)
    paths.changelog_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(paths.personal_vault_db) as conn:
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

    with sqlite3.connect(paths.state_tree_db) as conn:
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

    if not paths.references_json.exists():
        paths.references_json.write_text(
            json.dumps({"schema_version": "1.0", "references": []}, indent=2),
            encoding="utf-8",
        )


def load_reference_entries(paths: StudioPaths = PATHS) -> list[ReferenceEntry]:
    """Load non-sensitive domain references from references.json."""
    if not paths.references_json.exists():
        return []
    raw = json.loads(paths.references_json.read_text(encoding="utf-8"))
    items = raw.get("references", []) if isinstance(raw, dict) else []
    return [ReferenceEntry.model_validate(item) for item in items if isinstance(item, dict)]


def render_svg_tree(
    nodes: list[ContextNodeState],
    theme: UiThemeSpec | None = None,
) -> str:
    """Render an animated Gemini-aurora Yggdrasil SVG tree scaled by W_i weights."""
    palette = theme or UiThemeSpec()
    router = TrunkRouter(engine=LocalEngine.get_shared(LocalEngineConfig(model_name="yggdrasil-nano")))
    width, height = 760, 440
    center_x, trunk_base_y = width // 2, 390
    total = max(len(nodes), 1)
    dur = f"{palette.animation_duration_s:.1f}s"

    parts: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            'width="100%" height="100%" role="img" aria-label="Yggdrasil Context Tree">'
        ),
        "<defs>",
        '<radialGradient id="yggAura" cx="50%" cy="45%" r="55%">',
        f'<stop offset="0%" stop-color="{html.escape(palette.surface_panel)}"/>',
        f'<stop offset="100%" stop-color="{html.escape(palette.background_canvas)}"/>',
        "</radialGradient>",
        "</defs>",
        f'<rect width="{width}" height="{height}" rx="18" fill="url(#yggAura)"/>',
        (
            f'<line x1="{center_x}" y1="{trunk_base_y}" x2="{center_x}" y2="145" '
            f'stroke="{html.escape(palette.accent_secondary)}" stroke-width="10" '
            'stroke-linecap="round"/>'
        ),
    ]

    for idx, node in enumerate(nodes):
        decision = router.evaluate_node(node, allow_cloud=not node.contains_personal_vault_data)
        radius = max(10.0, min(28.0, 11.0 + decision.weight * 8.5))
        opacity = max(0.30, min(1.0, 0.35 + decision.weight * 0.45))
        fill = palette.accent_vault if decision.air_gap_blocked else palette.accent_primary
        spread = (idx - (total - 1) / 2.0) * 145.0
        node_x = center_x + spread
        node_y = 325.0 if decision.air_gap_blocked else 108.0
        anchor_y = trunk_base_y - 55 if decision.air_gap_blocked else 160
        label = html.escape(node.label)
        parts.append(
            f'<path d="M {center_x} {anchor_y} Q {(center_x + node_x) / 2:.1f} '
            f'{(anchor_y + node_y) / 2 - 18:.1f} {node_x:.1f} {node_y:.1f}" '
            f'fill="none" stroke="{html.escape(fill)}" stroke-opacity="{opacity:.2f}" '
            'stroke-width="3"/>'
        )
        parts.append(
            f'<circle cx="{node_x:.1f}" cy="{node_y:.1f}" r="{radius:.1f}" '
            f'fill="{html.escape(fill)}" fill-opacity="{opacity:.2f}">'
            f'<animate attributeName="r" values="{radius:.1f};{radius + 2.5:.1f};{radius:.1f}" '
            f'dur="{dur}" repeatCount="indefinite"/>'
            "</circle>"
        )
        parts.append(
            f'<text x="{node_x:.1f}" y="{node_y + radius + 16:.1f}" fill="#e2e8f0" '
            'font-family="Segoe UI, sans-serif" font-size="12" text-anchor="middle">'
            f"{label} (W={decision.weight:.2f})</text>"
        )

    parts.append("</svg>")
    return "\n".join(parts)


def collect_changelogs(paths: StudioPaths = PATHS) -> list[dict[str, str]]:
    """Return sorted changelog filenames and Markdown contents."""
    if not paths.changelog_dir.exists():
        return []
    items: list[dict[str, str]] = []
    for file_path in sorted(paths.changelog_dir.glob("*.md")):
        items.append(
            {
                "name": file_path.name,
                "content": file_path.read_text(encoding="utf-8"),
            }
        )
    return items


def collect_workspace_inventory(paths: StudioPaths = PATHS) -> dict[str, Any]:
    """Summarize organized folders (agents_and_lms, vaults, markdowns, user_content)."""
    def _list_rel(folder: Path) -> list[str]:
        if not folder.exists():
            return []
        return [
            str(p.relative_to(folder))
            for p in sorted(folder.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        ][:40]

    param_total = (
        len(DEFAULT_MICRO_WEIGHTS_1024["b1"])
        + len(DEFAULT_MICRO_WEIGHTS_1024["b2"])
        + sum(len(row) for row in DEFAULT_MICRO_WEIGHTS_1024["w1"])
        + sum(len(row) for row in DEFAULT_MICRO_WEIGHTS_1024["w2"])
        + 2
    )
    return {
        "mode": paths.mode,
        "root_dir": str(paths.root_dir),
        "agents_dir": str(paths.agents_dir),
        "micro_router_parameters": param_total,
        "vaults": _list_rel(paths.vaults_dir),
        "changelogs": [c["name"] for c in collect_changelogs(paths)],
        "markdowns_and_specs": _list_rel(paths.markdowns_dir),
        "user_content": _list_rel(paths.user_content_dir),
    }


def _drive_async(coro: Any) -> Any:
    """Execute async orchestrator coroutines cleanly inside or outside an active event loop."""
    try:
        return asyncio.run(coro)
    except OSError:
        try:
            return coro.send(None)
        except StopIteration as stop:
            return stop.value


def dispatch_studio_request(
    prompt: str,
    *,
    from_personal_vault: bool = False,
    user_confirmed_ui_handoff: bool = False,
    paths: StudioPaths = PATHS,
) -> dict[str, Any]:
    """Evaluate conditional [/userinterface] gate and route pre-grouped tags safely."""
    ensure_runtime_directories(paths)
    ui_agent = UserInterfaceNestedAgent()
    ui_result = ui_agent.evaluate_or_execute(
        UiAgentInput(
            request_id=f"ui-{int(datetime.now(UTC).timestamp())}",
            raw_instruction=prompt,
            user_confirmed_handoff=user_confirmed_ui_handoff,
        )
    )
    if ui_result.status == "handoff_confirmation_required":
        return {
            "kind": "ui_handoff_required",
            "ui_result": ui_result.model_dump(mode="json"),
            "report": None,
        }

    bundle = pre_group_prompt(
        raw_text=prompt,
        source_id="yggdrasil_studio_gui",
        from_personal_vault=from_personal_vault,
    )
    orchestrator = NestedModelOrchestrator(
        config=OrchestratorConfig(
            nano_model_name=os.getenv("YGGDRASIL_LOCAL_MODEL", "yggdrasil-nano"),
            references_json_path=str(paths.references_json),
        )
    )
    local_refs = load_reference_entries(paths)
    report = _drive_async(
        orchestrator.process_bundle(bundle=bundle, local_references=local_refs)
    )
    payload = {
        "kind": "executed",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "ui_result": ui_result.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
    }
    session_file = paths.user_content_dir / "brain" / "last_session.json"
    session_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def build_studio_html(theme: UiThemeSpec | None = None) -> str:
    """Render the self-contained Gemini-branded Yggdrasil Studio single-page HTML app."""
    palette = theme or UiThemeSpec()
    sample_nodes = [
        ContextNodeState(
            node_id="root-vault",
            label="personal_vault.db",
            initial_weight=1.0,
            elapsed_hours=0.5,
            resonance_count=2,
            contains_personal_vault_data=True,
        ),
        ContextNodeState(
            node_id="twig-micro",
            label="1K Micro-Router",
            initial_weight=0.95,
            elapsed_hours=0.2,
            resonance_count=3,
            contains_personal_vault_data=True,
        ),
        ContextNodeState(
            node_id="leaf-nano",
            label="yggdrasil-nano",
            initial_weight=0.88,
            elapsed_hours=1.0,
            resonance_count=1,
            contains_personal_vault_data=False,
        ),
        ContextNodeState(
            node_id="leaf-tools",
            label="8 Python Solvers",
            initial_weight=0.98,
            elapsed_hours=0.1,
            resonance_count=4,
            contains_personal_vault_data=False,
        ),
    ]
    svg_tree = render_svg_tree(sample_nodes, theme=palette)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(palette.brand_name)} — Sovereign AI Studio</title>
<style>
:root {{
  --bg: {html.escape(palette.background_canvas)};
  --surface: {html.escape(palette.surface_panel)};
  --surface-2: #172033;
  --border: #26334d;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --cyan: {html.escape(palette.accent_primary)};
  --violet: {html.escape(palette.accent_secondary)};
  --emerald: {html.escape(palette.accent_vault)};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: radial-gradient(circle at top right, #16223c 0%, var(--bg) 55%);
  color: var(--text); height: 100vh; display: flex; flex-direction: column;
}}
header {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 20px; border-bottom: 1px solid var(--border); background: rgba(17,24,39,0.88);
}}
.brand {{ display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 16px; }}
.spark {{
  width: 28px; height: 28px; border-radius: 9px;
  background: linear-gradient(135deg, var(--cyan), var(--violet));
  display: grid; place-items: center; color: #050811; font-weight: 800;
}}
.badges {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.pill {{
  font-size: 12px; padding: 4px 10px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
}}
.pill.vault {{ border-color: var(--emerald); color: var(--emerald); }}
.pill.ui {{ border-color: var(--violet); color: #c4b5fd; }}
.shell {{
  flex: 1; display: grid; grid-template-columns: 240px 1fr 390px; min-height: 0;
}}
aside, .inspector {{
  border-right: 1px solid var(--border); padding: 14px; overflow-y: auto;
  background: rgba(11, 17, 32, 0.72);
}}
.inspector {{ border-right: none; border-left: 1px solid var(--border); }}
.nav-btn {{
  width: 100%; text-align: left; background: transparent; color: var(--text);
  border: 1px solid transparent; padding: 9px 12px; border-radius: 10px;
  cursor: pointer; margin-bottom: 6px; font-size: 13px;
}}
.nav-btn:hover, .nav-btn.active {{
  background: var(--surface-2); border-color: var(--border); color: var(--cyan);
}}
main {{ display: flex; flex-direction: column; padding: 18px 24px; min-height: 0; }}
.hero {{
  background: linear-gradient(135deg, rgba(56,189,248,0.12), rgba(139,92,246,0.12));
  border: 1px solid var(--border); border-radius: 18px; padding: 18px 22px; margin-bottom: 14px;
}}
.hero h1 {{ margin: 0 0 6px; font-size: 22px; background: linear-gradient(90deg, var(--cyan), #c4b5fd); -webkit-background-clip: text; color: transparent; }}
.hero p {{ margin: 0; color: var(--muted); font-size: 13px; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }}
.chip {{
  font-size: 12px; padding: 5px 10px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--cyan);
}}
.chip:hover {{ border-color: var(--cyan); }}
.output-pane {{
  flex: 1; overflow-y: auto; border: 1px solid var(--border); border-radius: 14px;
  background: rgba(17,24,39,0.65); padding: 14px; margin-bottom: 12px; font-size: 13px;
}}
.composer {{
  border: 1px solid var(--border); border-radius: 16px; background: var(--surface);
  padding: 10px 12px; display: flex; flex-direction: column; gap: 8px;
}}
textarea {{
  width: 100%; min-height: 92px; resize: vertical; border: none; outline: none;
  background: transparent; color: var(--text); font-family: Consolas, monospace; font-size: 13px;
}}
.composer-bar {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; }}
button.primary {{
  background: linear-gradient(135deg, var(--cyan), var(--violet));
  color: #050811; font-weight: 700; border: none; border-radius: 10px;
  padding: 8px 16px; cursor: pointer;
}}
.handoff-box {{
  border: 1px solid #f59e0b; background: rgba(245,158,11,0.1);
  border-radius: 12px; padding: 12px; margin-bottom: 10px;
}}
pre {{ white-space: pre-wrap; word-break: break-word; background: #090d16; padding: 10px; border-radius: 10px; border: 1px solid var(--border); }}
@media (max-width: 1050px) {{ .shell {{ grid-template-columns: 1fr; }} aside, .inspector {{ display: none; }} }}
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="spark">Y</div>
    <div>{html.escape(palette.brand_name)} <span style="color:var(--muted);font-weight:400;font-size:12px">• {html.escape(palette.tagline)}</span></div>
  </div>
  <div class="badges">
    <span class="pill vault">Air-Gap Vault: LOCAL ONLY</span>
    <span class="pill">1K Router: 0 VRAM</span>
    <span class="pill ui">[/userinterface] Conditional Gate: ARMED</span>
  </div>
</header>
<div class="shell">
  <aside>
    <div style="font-size:11px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">Workspace Navigation</div>
    <button class="nav-btn active" onclick="showTab('studio')">Studio Prompt Canvas</button>
    <button class="nav-btn" onclick="showTab('changelogs')">Version Changelogs</button>
    <button class="nav-btn" onclick="showTab('inventory')">Files & User Content</button>
    <div style="margin-top:14px;font-size:11px;text-transform:uppercase;color:var(--muted);margin-bottom:6px;">Quick Presets</div>
    <button class="nav-btn" onclick="loadPreset('calc')">ChemEng Arrhenius + IMC</button>
    <button class="nav-btn" onclick="loadPreset('code')">AST Code Optimiser</button>
    <button class="nav-btn" onclick="loadPreset('ui_gate')">Test GUI Keyword Handoff</button>
    <button class="nav-btn" onclick="loadPreset('ui_direct')">[/userinterface] Theme Preview</button>
  </aside>
  <main>
    <div id="tab-studio" style="display:flex;flex-direction:column;flex:1;min-height:0;">
      <div class="hero">
        <h1>Yggdrasil Sovereign Hybrid Studio</h1>
        <p>Token-conserving pre-grouped tag execution: pure Python deterministic solvers first (&lt;1 ms, 0 tokens), nested 1K micro-router + <code>yggdrasil-nano</code> fallback, strict <code>personal_vault.db</code> air-gap.</p>
      </div>
      <div class="chips">
        <span class="chip" onclick="insertTag('#TABLE_DATA')">#TABLE_DATA</span>
        <span class="chip" onclick="insertTag('#CALC_SOLVE')">#CALC_SOLVE</span>
        <span class="chip" onclick="insertTag('#DATA_COMPARE')">#DATA_COMPARE</span>
        <span class="chip" onclick="insertTag('#PDF_CONVERT')">#PDF_CONVERT</span>
        <span class="chip" onclick="insertTag('#SMART_PDF_LINK')">#SMART_PDF_LINK</span>
        <span class="chip" onclick="insertTag('#CODE_OPTIMISE')">#CODE_OPTIMISE</span>
        <span class="chip" onclick="insertTag('#CONTROL_SYSTEM')">#CONTROL_SYSTEM</span>
        <span class="chip" onclick="insertTag('#RESEARCH_GAP')">#RESEARCH_GAP</span>
        <span class="chip" style="color:#c4b5fd" onclick="insertTag('[/userinterface]')">[/userinterface]</span>
      </div>
      <div id="output" class="output-pane">Ready. Paste a tagged prompt or pick a preset on the left, then press <strong>Ctrl+Enter</strong>.</div>
      <div class="composer">
        <textarea id="promptInput" placeholder="#CALC_SOLVE: Arrhenius mode=arrhenius A=1e8 Ea=50000 T=350&#10;1e8 * exp(-50000 / (8.31446261815324 * 350))"></textarea>
        <div class="composer-bar">
          <label style="font-size:12px;color:var(--muted)"><input type="checkbox" id="vaultToggle" checked/> Treat as Air-Gapped Local Context</label>
          <button class="primary" onclick="runPrompt(false)">Execute Pipeline (Ctrl+Enter)</button>
        </div>
      </div>
    </div>
    <div id="tab-changelogs" style="display:none;overflow-y:auto;flex:1;"></div>
    <div id="tab-inventory" style="display:none;overflow-y:auto;flex:1;"></div>
  </main>
  <section class="inspector">
    <div style="font-size:11px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">Animated Yggdrasil Tree (W_i)</div>
    <div id="svgBox">{svg_tree}</div>
    <div style="margin-top:12px;font-size:12px;color:var(--muted);" id="telemetryNote">
      Green roots = air-gapped local execution; Cyan leaves = sanitized capability layer.
    </div>
  </section>
</div>
<script>
const PRESETS = {{
  calc: "#CALC_SOLVE: Arrhenius\\nmode=arrhenius\\n1e8 * exp(-50000 / (8.31446261815324 * 350))\\n[/#CALC_SOLVE]\\n#CONTROL_SYSTEM: CSTR IMC PID\\nkp=2.0 tau=10.0 theta=2.0 controller_type=PID tuning_method=imc imc_tau_c=2.0",
  code: "#CODE_OPTIMISE: Async Audit\\nimport time\\nasync def poll():\\n    time.sleep(1)\\n    return 1",
  ui_gate: "Adjust the GUI theme appearance and animation timing",
  ui_direct: "[/userinterface] Apply compact dark mode with fast animation"
}};
function loadPreset(key) {{
  document.getElementById('promptInput').value = PRESETS[key];
  showTab('studio');
}}
function insertTag(tag) {{
  const ta = document.getElementById('promptInput');
  ta.value = tag + ": \\n" + ta.value;
  ta.focus();
}}
async function showTab(name) {{
  ['studio','changelogs','inventory'].forEach(t => {{
    document.getElementById('tab-' + t).style.display = (t === name) ? (t === 'studio' ? 'flex' : 'block') : 'none';
  }});
  if (name === 'changelogs') {{
    const res = await fetch('/api/changelogs'); const data = await res.json();
    document.getElementById('tab-changelogs').innerHTML = data.map(c => `<h3>${{c.name}}</h3><pre>${{c.content.replace(/</g,'&lt;')}}</pre>`).join('');
  }} else if (name === 'inventory') {{
    const res = await fetch('/api/state'); const data = await res.json();
    document.getElementById('tab-inventory').innerHTML = `<h3>Self-Sufficient Directory Inventory</h3><pre>${{JSON.stringify(data, null, 2)}}</pre>`;
  }}
}}
async function runPrompt(confirmedUi) {{
  const prompt = document.getElementById('promptInput').value;
  const fromVault = document.getElementById('vaultToggle').checked;
  const out = document.getElementById('output');
  out.innerHTML = 'Running deterministic/nano pipeline...';
  const res = await fetch('/api/dispatch', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{prompt, from_personal_vault: fromVault, user_confirmed_ui_handoff: confirmedUi}})
  }});
  const data = await res.json();
  if (data.kind === 'ui_handoff_required') {{
    out.innerHTML = `<div class="handoff-box"><strong>[/userinterface] Conditional Gate Triggered</strong><p>${{data.ui_result.handoff_decision.handoff_prompt}}</p><button class="primary" onclick="runPrompt(true)">Confirm Handover to [/userinterface]</button></div>`;
    return;
  }}
  out.innerHTML = `<pre>${{JSON.stringify(data, null, 2)}}</pre>`;
}}
document.getElementById('promptInput').addEventListener('keydown', e => {{
  if (e.ctrlKey && e.key === 'Enter') runPrompt(false);
}});
</script>
</body>
</html>"""


class StudioHttpHandler(BaseHTTPRequestHandler):
    """HTTP handler serving Yggdrasil Studio UI and local deterministic APIs."""

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            body = build_studio_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/state":
            self._send_json(collect_workspace_inventory(PATHS))
            return
        if path == "/api/changelogs":
            self._send_json(collect_changelogs(PATHS))
            return
        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/dispatch":
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        parsed = json.loads(body)
        prompt = str(parsed.get("prompt", ""))
        from_vault = bool(parsed.get("from_personal_vault", True))
        confirmed_ui = bool(parsed.get("user_confirmed_ui_handoff", False))
        result = dispatch_studio_request(
            prompt,
            from_personal_vault=from_vault,
            user_confirmed_ui_handoff=confirmed_ui,
            paths=PATHS,
        )
        self._send_json(result)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _open_studio_window(url: str) -> None:
    """Open Studio UI in Chromium app-mode window when installed, else default browser."""
    for browser in ("msedge", "chrome"):
        exe = shutil.which(browser)
        if exe:
            subprocess.Popen([exe, f"--app={url}"])
            return
    webbrowser.open(url)


def run_self_test(paths: StudioPaths = PATHS) -> dict[str, Any]:
    """Run non-blocking standalone self-test verifying paths, UI gate, tools, and HTML snapshot."""
    ensure_runtime_directories(paths)
    snapshot_html = build_studio_html()
    snapshot_path = paths.user_content_dir / "brain" / "studio_snapshot.html"
    snapshot_path.write_text(snapshot_html, encoding="utf-8")

    ui_blocked = dispatch_studio_request(
        "Update GUI visual theme",
        from_personal_vault=False,
        user_confirmed_ui_handoff=False,
        paths=paths,
    )
    ui_allowed = dispatch_studio_request(
        "[/userinterface] Apply compact dark mode\n"
        "#CALC_SOLVE: Arrhenius\n1e8 * exp(-50000 / (8.31446261815324 * 350))\n[/#CALC_SOLVE]\n"
        "#CONTROL_SYSTEM: Loop\nkp=2.0 tau=10.0 theta=2.0",
        from_personal_vault=False,
        paths=paths,
    )
    inventory = collect_workspace_inventory(paths)
    LocalEngine._instance = None
    return {
        "mode": paths.mode,
        "script_path": str(Path(__file__).resolve()),
        "yggdrasil_agents_file": str(Path(sys.modules["yggdrasil_agents"].__file__ or "")),
        "ui_gate_blocked_status": ui_blocked["ui_result"]["status"],
        "ui_gate_allowed_status": ui_allowed["ui_result"]["status"],
        "deterministic_hits": ui_allowed["report"]["deterministic_hits"],
        "snapshot_bytes": len(snapshot_html.encode("utf-8")),
        "snapshot_path": str(snapshot_path),
        "inventory": inventory,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yggdrasil Sovereign AI Studio Launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--self-test", action="store_true", help="Verify standalone studio & exit")
    parser.add_argument("--no-browser", action="store_true", help="Serve without opening browser")
    args = parser.parse_args(argv)

    if args.self_test:
        print(json.dumps(run_self_test(PATHS), indent=2))
        return 0

    ensure_runtime_directories(PATHS)
    server = ThreadingHTTPServer((args.host, args.port), StudioHttpHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Yggdrasil Studio running in {PATHS.mode} mode at {url}")
    if not args.no_browser:
        threading.Timer(0.6, _open_studio_window, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
