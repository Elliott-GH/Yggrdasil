"""Exported registry and callable interface for Yggdrasil lightweight models and tools.

Exposes the extreme-lightweight ~1,024-parameter deterministic router, Modelfile-backed
`yggdrasil-nano` callable agent, and all 8 pure-Python deterministic domain solvers.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
_STANDALONE_AGENTS = APP_DIR.parent / "agents_and_lms"
FOUNDRY_DIR = (
    _STANDALONE_AGENTS
    if (_STANDALONE_AGENTS / "yggdrasil_agents").is_dir()
    else APP_DIR.parent / "03-agent-foundry"
)
if str(FOUNDRY_DIR) not in sys.path:
    sys.path.insert(0, str(FOUNDRY_DIR))

from yggdrasil_agents.nano_models import (
    DEFAULT_MICRO_WEIGHTS_1024,
    DETERMINISTIC_TAGS,
    NestedCallableLightAgent,
    NestedModelOrchestrator,
    OrchestratorConfig,
    OrchestratorExecutionReport,
    PreGroupedBundle,
    ReferenceEntry,
    TagType,
    ThousandParamMicroModel,
    calculation_solver_function,
    coding_optimiser_function,
    control_system_optimiser_function,
    data_comparison_function,
    data_handling_function,
    pdf_converter_function,
    pre_group_prompt,
    research_tool_function,
    smart_pdf_handling_function,
)

_STANDALONE_VAULTS = APP_DIR.parent / "data_and_vaults"
DEFAULT_REFERENCES_PATH = (
    (_STANDALONE_VAULTS / "references.json")
    if _STANDALONE_VAULTS.is_dir()
    else (APP_DIR / "vaults" / "references.json")
)


class ExportedAgentDescriptor(BaseModel):
    """Metadata entry describing an exported Yggdrasil lightweight model or tool."""

    agent_id: str
    tag: str
    callable_name: str
    execution_mode: str
    parameter_count: int = Field(ge=0)
    vram_mb_estimate: int = Field(ge=0)
    llm_tokens_required: bool


EXPORTED_NANO_AGENTS: dict[str, Callable[..., Any]] = {
    TagType.TABLE_DATA.value: data_handling_function,
    TagType.CALC_SOLVE.value: calculation_solver_function,
    TagType.DATA_COMPARE.value: data_comparison_function,
    TagType.PDF_CONVERT.value: pdf_converter_function,
    TagType.SMART_PDF_LINK.value: smart_pdf_handling_function,
    TagType.CODE_OPTIMISE.value: coding_optimiser_function,
    TagType.CONTROL_SYSTEM.value: control_system_optimiser_function,
    TagType.RESEARCH_GAP.value: research_tool_function,
    "micro_router_1024": ThousandParamMicroModel,
    "nano_slice_llm": NestedCallableLightAgent,
    "nested_orchestrator": NestedModelOrchestrator,
}


def get_exported_nano_manifest() -> list[ExportedAgentDescriptor]:
    """Return a structured manifest of all exported lightweight models and pure-Python tools."""
    return [
        ExportedAgentDescriptor(
            agent_id="micro_router_1024",
            tag="ALL",
            callable_name="ThousandParamMicroModel",
            execution_mode="pure_python_cpu",
            parameter_count=len(DEFAULT_MICRO_WEIGHTS_1024["b1"])
            + len(DEFAULT_MICRO_WEIGHTS_1024["b2"])
            + sum(len(r) for r in DEFAULT_MICRO_WEIGHTS_1024["w1"])
            + sum(len(r) for r in DEFAULT_MICRO_WEIGHTS_1024["w2"])
            + 2,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="table_data_solver",
            tag=TagType.TABLE_DATA.value,
            callable_name="data_handling_function",
            execution_mode="pure_python_deterministic",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="calculation_solver",
            tag=TagType.CALC_SOLVE.value,
            callable_name="calculation_solver_function",
            execution_mode="pure_python_deterministic",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="data_comparison_solver",
            tag=TagType.DATA_COMPARE.value,
            callable_name="data_comparison_function",
            execution_mode="pure_python_deterministic",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="pdf_converter_solver",
            tag=TagType.PDF_CONVERT.value,
            callable_name="pdf_converter_function",
            execution_mode="pure_python_deterministic",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="smart_pdf_linker",
            tag=TagType.SMART_PDF_LINK.value,
            callable_name="smart_pdf_handling_function",
            execution_mode="pure_python_deterministic",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="coding_optimiser",
            tag=TagType.CODE_OPTIMISE.value,
            callable_name="coding_optimiser_function",
            execution_mode="pure_python_ast",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="control_system_optimiser",
            tag=TagType.CONTROL_SYSTEM.value,
            callable_name="control_system_optimiser_function",
            execution_mode="pure_python_control",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="research_gap_verifier",
            tag=TagType.RESEARCH_GAP.value,
            callable_name="research_tool_function",
            execution_mode="pure_python_airgap_guarded",
            parameter_count=0,
            vram_mb_estimate=0,
            llm_tokens_required=False,
        ),
        ExportedAgentDescriptor(
            agent_id="yggdrasil_nano_llm",
            tag=TagType.SEMANTIC_MICRO.value,
            callable_name="NestedCallableLightAgent",
            execution_mode="ollama_shared_local_engine",
            parameter_count=135_000_000,
            vram_mb_estimate=270,
            llm_tokens_required=True,
        ),
    ]


def load_reference_entries(references_path: Path = DEFAULT_REFERENCES_PATH) -> list[ReferenceEntry]:
    """Load validated non-sensitive ReferenceEntry items from vaults/references.json."""
    if not references_path.exists():
        return []
    with references_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        return []
    items = raw.get("references", [])
    if not isinstance(items, list):
        return []
    return [ReferenceEntry.model_validate(entry) for entry in items if isinstance(entry, dict)]


async def run_pre_tagged_workflow(
    raw_prompt: str,
    source_id: str = "app_workflow",
    from_personal_vault: bool = True,
    allow_cloud_synthesis: bool = False,
    allow_external_research: bool = False,
    references_path: Path = DEFAULT_REFERENCES_PATH,
) -> OrchestratorExecutionReport:
    """Slice a prompt by pre-grouped tags and execute via NestedModelOrchestrator."""
    local_refs = load_reference_entries(references_path)
    orchestrator = NestedModelOrchestrator(
        config=OrchestratorConfig(
            allow_cloud_synthesis=allow_cloud_synthesis,
            allow_external_research=allow_external_research,
            references_json_path=str(references_path),
        )
    )
    bundle: PreGroupedBundle = pre_group_prompt(
        raw_text=raw_prompt,
        source_id=source_id,
        from_personal_vault=from_personal_vault,
        micro_model=orchestrator.micro_model,
    )
    return await orchestrator.process_bundle(
        bundle=bundle,
        local_references=local_refs,
        cloud_synthesis_requested=allow_cloud_synthesis,
    )


def _run_coro_sync(coro: Any) -> Any:
    """Drive a non-blocking coroutine cleanly if no network/event loop I/O socket is required."""
    try:
        return coro.send(None)
    except StopIteration as stop:
        return stop.value


def run_demo_suite() -> dict[str, Any]:
    """Execute an end-to-end deterministic 8-tag demonstration using 0 LLM tokens."""
    demo_prompt = """
#TABLE_DATA: Reactor Run Telemetry
run,temp_k,conversion
R1,320,0.42
R2,340,0.68
R3,360,0.85
[/#TABLE_DATA]

#CALC_SOLVE: Arrhenius Reaction Rate mode=arrhenius A=1.2e8 Ea=52000 T=350
k = 1.2e8 * exp(-52000 / (8.31446261815324 * 350))
[/#CALC_SOLVE]

#DATA_COMPARE: Model vs Plant Yield
baseline: 0.42, 0.68, 0.85
candidate: 0.43, 0.67, 0.86
[/#DATA_COMPARE]

#PDF_CONVERT: Reactor Kinetics Paper Notes
Journal of Kinetics - Page 1
The thermo-
dynamics of exothermic CSTR loops.
---PAGE---
Journal of Kinetics - Page 1
Continued reaction rate discussion DOI 10.1021/i200032a041.
[/#PDF_CONVERT]

#SMART_PDF_LINK: Cross-Reference Section Linker query=IMC PID tuning
# Section 1 Introduction
Internal model control [1] governs FOPDT loops as shown in Table 1 and Eq. 2.
---PAGE---
# Section 2 Tuning Rules
See Fig. 1 for step performance under IMC PID tuning [2].
[/#SMART_PDF_LINK]

#CODE_OPTIMISE: Async Pipeline Static Audit
async def poll_sensor(url: str) -> str:
    return url
[/#CODE_OPTIMISE]

#CONTROL_SYSTEM: FOPDT IMC Tuning
kp=2.0 tau=10.0 theta=2.0 controller_type=PID tuning_method=imc imc_tau_c=2.0
[/#CONTROL_SYSTEM]

#RESEARCH_GAP: Verify IMC FOPDT Literature Coverage
Internal model control for FOPDT systems improves robustness over classical Ziegler-Nichols tuning.
[/#RESEARCH_GAP]
"""
    report: OrchestratorExecutionReport = _run_coro_sync(
        run_pre_tagged_workflow(
            demo_prompt,
            source_id="exported_nano_demo",
            from_personal_vault=False,
        )
    )
    return {
        "deterministic_tags_count": len(DETERMINISTIC_TAGS),
        "manifest_count": len(get_exported_nano_manifest()),
        "bundle_id": report.bundle_id,
        "total_slices": report.total_slices,
        "deterministic_hits": report.deterministic_hits,
        "nano_llm_calls": report.nano_llm_calls,
        "token_savings_ratio": round(report.token_savings_ratio, 4),
        "total_latency_ms": round(report.total_latency_ms, 3),
        "tiers": [
            {
                "slice_id": r.slice_id,
                "tag": r.tag.value,
                "tier": r.execution_tier,
                "llm_tokens_used": r.llm_tokens_used,
            }
            for r in report.results
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run_demo_suite(), indent=2))
