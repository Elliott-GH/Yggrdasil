"""Nested model orchestrator routing pre-grouped DataSlices (SPEC-001 Section 4.3)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from .deterministic_tools import (
    CalculationSolverInput,
    CodingOptimiserInput,
    ControlSystemInput,
    DataComparisonInput,
    FopdtModelParams,
    PdfConverterInput,
    PdfPageArtifact,
    ReferenceEntry,
    ResearchToolInput,
    SmartPdfInput,
    TableHandlingInput,
    calculation_solver_function,
    coding_optimiser_function,
    control_system_optimiser_function,
    data_comparison_function,
    data_handling_function,
    pdf_converter_function,
    research_tool_function,
    smart_pdf_handling_function,
)
from .leaves import LeafCloudSynthesis, LeavesCloudAgent, SanitizedCloudRequest
from .local_engine import LocalEngine, LocalEngineConfig
from .micro_model import MicroModelPrediction, ThousandParamMicroModel
from .nano_agent import (
    NanoSliceInferenceInput,
    NanoSliceInferenceOutput,
    NestedCallableLightAgent,
)
from .pre_slicer import (
    DETERMINISTIC_TAGS,
    DataSlice,
    PreGroupedBundle,
    TagType,
    pre_group_prompt,
)
from .trunk import ContextNodeState, DecayParameters, TrunkRouter, compute_decay_weight
from .twigs import TwigsExecutor, TwigTaskInput

ExecutionTier = Literal[
    "deterministic_python",
    "nano_local_llm",
    "twigs_local_llm",
    "leaves_cloud",
    "air_gap_blocked",
]

_NUM_LIST_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


class OrchestratorConfig(BaseModel):
    """Configuration governing nested routing, decay math, and air-gap policy."""

    allow_cloud_synthesis: bool = False
    allow_external_research: bool = False
    decay_parameters: DecayParameters = Field(default_factory=DecayParameters)
    semantic_escalation_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    nano_model_name: str = "yggdrasil-nano"
    strict_raise_on_cloud_taint: bool = False
    references_json_path: str | None = None


class SliceExecutionResult(BaseModel):
    """Per-slice execution trace and validated output from NestedModelOrchestrator."""

    slice_id: str
    tag: TagType
    execution_tier: ExecutionTier
    weight_wi: float = Field(ge=0.0)
    should_prune: bool = False
    deterministic_output: BaseModel | None = None
    nano_output: NanoSliceInferenceOutput | None = None
    cloud_output: LeafCloudSynthesis | None = None
    air_gap_blocked: bool = False
    llm_tokens_used: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    error: str | None = None


class OrchestratorExecutionReport(BaseModel):
    """Aggregated telemetry and slice outputs for an entire PreGroupedBundle."""

    bundle_id: str
    total_slices: int = Field(ge=0)
    deterministic_hits: int = Field(ge=0)
    nano_llm_calls: int = Field(ge=0)
    cloud_calls: int = Field(ge=0)
    air_gap_blocks: int = Field(ge=0)
    token_savings_ratio: float = Field(ge=0.0, le=1.0)
    results: list[SliceExecutionResult] = Field(default_factory=list)
    total_latency_ms: float = Field(default=0.0, ge=0.0)


def _try_parse_json_dict(raw_payload: str) -> dict[str, Any] | None:
    stripped = raw_payload.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_float_series(raw_text: str) -> list[float]:
    return [float(tok) for tok in _NUM_LIST_RE.findall(raw_text)]


def _parse_kv_lines(raw_payload: str, structured_kv: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(structured_kv)
    for line in raw_payload.splitlines():
        if "=" not in line:
            continue
        for token in line.split():
            if "=" not in token:
                continue
            key, val = token.split("=", 1)
            key = key.strip()
            val = val.strip().rstrip(",")
            if not key:
                continue
            try:
                merged[key] = float(val) if ("." in val or "e" in val.lower()) else int(val)
            except ValueError:
                if val.lower() == "true":
                    merged[key] = True
                elif val.lower() == "false":
                    merged[key] = False
                else:
                    merged[key] = val.strip("\"'")
    return merged


def _build_table_input(slice_obj: DataSlice) -> TableHandlingInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        merged["contains_personal_vault_data"] = bool(
            slice_obj.contains_personal_vault_data or merged.get("contains_personal_vault_data", False)
        )
        return TableHandlingInput.model_validate(merged)

    kv = slice_obj.structured_kv
    return TableHandlingInput(
        slice_id=slice_obj.slice_id,
        raw_table=slice_obj.raw_payload,
        input_format=str(kv.get("format", kv.get("input_format", "auto"))),  # type: ignore[arg-type]
        sort_by_column=str(kv["sort_by_column"]) if "sort_by_column" in kv else None,
        group_by_column=str(kv["group_by_column"]) if "group_by_column" in kv else None,
        filter_column=str(kv["filter_column"]) if "filter_column" in kv else None,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
    )


def _build_calc_input(slice_obj: DataSlice) -> CalculationSolverInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        merged["contains_personal_vault_data"] = bool(
            slice_obj.contains_personal_vault_data or merged.get("contains_personal_vault_data", False)
        )
        return CalculationSolverInput.model_validate(merged)

    kv = slice_obj.structured_kv
    mode = str(kv.get("mode", "evaluate_expression"))
    expr = slice_obj.raw_payload.strip()
    if mode == "evaluate_expression" and "=" in expr and "\n" not in expr:
        _, rhs = expr.split("=", 1)
        if rhs.strip():
            expr = rhs.strip()
    variables = {
        k: float(v)
        for k, v in kv.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    return CalculationSolverInput(
        slice_id=slice_obj.slice_id,
        mode=mode,  # type: ignore[arg-type]
        expression=expr,
        variables=variables,
        parameters=variables,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
    )


def _build_compare_input(slice_obj: DataSlice) -> DataComparisonInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        merged["contains_personal_vault_data"] = bool(
            slice_obj.contains_personal_vault_data or merged.get("contains_personal_vault_data", False)
        )
        return DataComparisonInput.model_validate(merged)

    lines = [ln.strip() for ln in slice_obj.raw_payload.splitlines() if ln.strip()]
    baseline: list[float] = []
    candidate: list[float] = []
    for ln in lines:
        lower = ln.lower()
        nums = _parse_float_series(ln)
        if not nums:
            continue
        if "baseline" in lower and not baseline:
            baseline = nums
        elif "candidate" in lower and not candidate:
            candidate = nums
        elif not baseline:
            baseline = nums
        elif not candidate:
            candidate = nums
    if not baseline or not candidate:
        all_nums = _parse_float_series(slice_obj.raw_payload)
        half = len(all_nums) // 2
        if half >= 1:
            baseline = all_nums[:half]
            candidate = all_nums[half : half * 2]
    return DataComparisonInput(
        slice_id=slice_obj.slice_id,
        comparison_mode="numeric_series",
        baseline_series=baseline,
        candidate_series=candidate,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
    )


def _build_pdf_convert_input(slice_obj: DataSlice) -> PdfConverterInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        merged["contains_personal_vault_data"] = bool(
            slice_obj.contains_personal_vault_data or merged.get("contains_personal_vault_data", False)
        )
        return PdfConverterInput.model_validate(merged)

    kv = slice_obj.structured_kv
    if "source_path" in kv:
        return PdfConverterInput(
            slice_id=slice_obj.slice_id,
            source_path=str(kv["source_path"]),
            contains_personal_vault_data=slice_obj.contains_personal_vault_data,
        )
    raw = slice_obj.raw_payload
    if "\f" in raw:
        pages = [p for p in raw.split("\f") if p.strip()]
    elif "---PAGE---" in raw:
        pages = [p for p in raw.split("---PAGE---") if p.strip()]
    else:
        pages = [raw]
    return PdfConverterInput(
        slice_id=slice_obj.slice_id,
        raw_extracted_pages=pages,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
    )


def _build_smart_pdf_input(slice_obj: DataSlice) -> SmartPdfInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        merged["contains_personal_vault_data"] = bool(
            slice_obj.contains_personal_vault_data or merged.get("contains_personal_vault_data", False)
        )
        return SmartPdfInput.model_validate(merged)

    kv = slice_obj.structured_kv
    raw_pages = [p.strip() for p in re.split(r"\f|---PAGE---", slice_obj.raw_payload) if p.strip()]
    if not raw_pages:
        raw_pages = [slice_obj.raw_payload]
    pages = [
        PdfPageArtifact(
            page_number=idx + 1,
            char_count=len(text),
            word_count=len(text.split()),
            extracted_text=text,
        )
        for idx, text in enumerate(raw_pages)
    ]
    return SmartPdfInput(
        slice_id=slice_obj.slice_id,
        pages=pages,
        query=str(kv["query"]) if "query" in kv else None,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
    )


def _build_code_optimiser_input(slice_obj: DataSlice) -> CodingOptimiserInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        merged["contains_personal_vault_data"] = bool(
            slice_obj.contains_personal_vault_data or merged.get("contains_personal_vault_data", False)
        )
        return CodingOptimiserInput.model_validate(merged)

    code = slice_obj.raw_payload.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            code = "\n".join(lines[1:-1])
        else:
            code = "\n".join(lines[1:])
    return CodingOptimiserInput(
        slice_id=slice_obj.slice_id,
        source_code=code,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
    )


def _build_control_input(slice_obj: DataSlice) -> ControlSystemInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        merged["contains_personal_vault_data"] = bool(
            slice_obj.contains_personal_vault_data or merged.get("contains_personal_vault_data", False)
        )
        return ControlSystemInput.model_validate(merged)

    params = _parse_kv_lines(slice_obj.raw_payload, slice_obj.structured_kv)
    fopdt: FopdtModelParams | None = None
    if all(k in params for k in ("kp", "tau", "theta")):
        fopdt = FopdtModelParams(
            kp=float(params["kp"]),
            tau=float(params["tau"]),
            theta=float(params["theta"]),
        )
    controller_type = str(params.get("controller_type", "PID"))
    tuning_method = str(params.get("tuning_method", "imc"))
    return ControlSystemInput(
        slice_id=slice_obj.slice_id,
        fopdt=fopdt,
        controller_type=controller_type,  # type: ignore[arg-type]
        tuning_method=tuning_method,  # type: ignore[arg-type]
        imc_tau_c=float(params["imc_tau_c"]) if "imc_tau_c" in params else None,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
    )


def _build_research_input(
    slice_obj: DataSlice,
    local_references: list[ReferenceEntry] | None,
    references_json_path: str | None,
    allow_external_research: bool,
) -> ResearchToolInput:
    json_body = _try_parse_json_dict(slice_obj.raw_payload)
    if json_body is not None:
        merged = dict(json_body)
        merged["slice_id"] = slice_obj.slice_id
        tainted = bool(
            slice_obj.contains_personal_vault_data
            or merged.get("contains_personal_vault_data", False)
        )
        merged["contains_personal_vault_data"] = tainted
        merged["privacy_tier"] = "air_gapped" if tainted else merged.get("privacy_tier", slice_obj.privacy_tier)
        if local_references and not merged.get("local_references"):
            merged["local_references"] = [ref.model_dump() for ref in local_references]
        if references_json_path and not merged.get("references_json_path"):
            merged["references_json_path"] = references_json_path
        return ResearchToolInput.model_validate(merged)

    kv = slice_obj.structured_kv
    raw_terms = kv.get("query_terms")
    query_terms = list(raw_terms) if isinstance(raw_terms, list) else []
    allow_ext = bool(allow_external_research and not slice_obj.contains_personal_vault_data)
    return ResearchToolInput(
        slice_id=slice_obj.slice_id,
        research_text=slice_obj.raw_payload,
        query_terms=[str(t) for t in query_terms],
        local_references=list(local_references) if local_references else [],
        references_json_path=references_json_path,
        allow_external_lookup=allow_ext,
        contains_personal_vault_data=slice_obj.contains_personal_vault_data,
        privacy_tier=slice_obj.privacy_tier,
    )


class NestedModelOrchestrator:
    """Routes PreGroupedBundle slices across pure Python, nano LLM, Twigs, and Leaves."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        engine: LocalEngine | None = None,
        micro_model: ThousandParamMicroModel | None = None,
        trunk_router: TrunkRouter | None = None,
        nano_agent: NestedCallableLightAgent | None = None,
        twigs_executor: TwigsExecutor | None = None,
        leaves_agent: LeavesCloudAgent | None = None,
    ) -> None:
        self.config: OrchestratorConfig = config or OrchestratorConfig()
        self._engine: LocalEngine | None = engine
        self.micro_model: ThousandParamMicroModel = micro_model or ThousandParamMicroModel()
        self._trunk_router: TrunkRouter | None = trunk_router
        self._nano_agent: NestedCallableLightAgent | None = nano_agent
        self._twigs_executor: TwigsExecutor | None = twigs_executor
        self._leaves_agent: LeavesCloudAgent | None = leaves_agent

    def _get_engine(self) -> LocalEngine:
        if self._engine is None:
            self._engine = LocalEngine.get_shared(
                LocalEngineConfig(model_name=self.config.nano_model_name)
            )
        return self._engine

    def _get_nano_agent(self) -> NestedCallableLightAgent:
        if self._nano_agent is None:
            self._nano_agent = NestedCallableLightAgent(engine=self._get_engine())
        return self._nano_agent

    def _get_twigs_executor(self) -> TwigsExecutor:
        if self._twigs_executor is None:
            self._twigs_executor = TwigsExecutor(engine=self._get_engine())
        return self._twigs_executor

    def _get_leaves_agent(self) -> LeavesCloudAgent:
        if self._leaves_agent is None:
            self._leaves_agent = LeavesCloudAgent()
        return self._leaves_agent

    def _evaluate_weight_and_prune(self, slice_obj: DataSlice) -> tuple[float, bool]:
        if self._trunk_router is not None:
            node = ContextNodeState(
                node_id=slice_obj.slice_id,
                label=slice_obj.title or slice_obj.tag.value,
                initial_weight=slice_obj.priority_weight,
                contains_personal_vault_data=slice_obj.contains_personal_vault_data,
            )
            decision = self._trunk_router.evaluate_node(node, allow_cloud=False)
            return decision.weight, decision.should_prune

        weight = compute_decay_weight(
            initial_weight=slice_obj.priority_weight,
            decay_rate=self.config.decay_parameters.decay_rate,
            elapsed_hours=0.0,
            alpha=self.config.decay_parameters.alpha,
            resonance_count=0,
        )
        return weight, weight < self.config.decay_parameters.prune_threshold

    async def _execute_deterministic_slice(
        self,
        slice_obj: DataSlice,
        local_references: list[ReferenceEntry] | None,
    ) -> BaseModel:
        tag = slice_obj.tag
        if tag == TagType.TABLE_DATA:
            return data_handling_function(_build_table_input(slice_obj))
        if tag == TagType.CALC_SOLVE:
            return calculation_solver_function(_build_calc_input(slice_obj))
        if tag == TagType.DATA_COMPARE:
            return data_comparison_function(_build_compare_input(slice_obj))
        if tag == TagType.PDF_CONVERT:
            pdf_in = _build_pdf_convert_input(slice_obj)
            if pdf_in.source_path is not None:
                return await asyncio.to_thread(pdf_converter_function, pdf_in)
            return pdf_converter_function(pdf_in)
        if tag == TagType.SMART_PDF_LINK:
            return smart_pdf_handling_function(_build_smart_pdf_input(slice_obj))
        if tag == TagType.CODE_OPTIMISE:
            return coding_optimiser_function(_build_code_optimiser_input(slice_obj))
        if tag == TagType.CONTROL_SYSTEM:
            return control_system_optimiser_function(_build_control_input(slice_obj))
        if tag == TagType.RESEARCH_GAP:
            research_in = _build_research_input(
                slice_obj,
                local_references=local_references,
                references_json_path=self.config.references_json_path,
                allow_external_research=self.config.allow_external_research,
            )
            return await research_tool_function(research_in)
        raise ValueError(f"Unsupported deterministic tag: {tag.value}")

    async def process_bundle(
        self,
        bundle: PreGroupedBundle,
        local_references: list[ReferenceEntry] | None = None,
        cloud_synthesis_requested: bool = False,
    ) -> OrchestratorExecutionReport:
        """Execute each isolated DataSlice using the deterministic-first SPEC-001 cascade."""
        t_bundle_start = time.perf_counter()
        results: list[SliceExecutionResult] = []
        det_hits = 0
        nano_calls = 0
        cloud_calls = 0
        air_gap_blocks = 0

        for slice_obj in bundle.slices:
            t_slice_start = time.perf_counter()
            weight_wi, should_prune = self._evaluate_weight_and_prune(slice_obj)
            prediction: MicroModelPrediction = self.micro_model.predict(
                slice_obj,
                has_explicit_tag=True,
            )

            # Tier 1: Deterministic pure-Python solver (0 VRAM, 0 LLM tokens).
            if slice_obj.tag in DETERMINISTIC_TAGS and slice_obj.can_execute_in_pure_python:
                det_out = await self._execute_deterministic_slice(slice_obj, local_references)
                det_hits += 1
                results.append(
                    SliceExecutionResult(
                        slice_id=slice_obj.slice_id,
                        tag=slice_obj.tag,
                        execution_tier="deterministic_python",
                        weight_wi=weight_wi,
                        should_prune=should_prune,
                        deterministic_output=det_out,
                        air_gap_blocked=False,
                        llm_tokens_used=0,
                        latency_ms=(time.perf_counter() - t_slice_start) * 1000.0,
                    )
                )
                continue

            # Tier 2: Strict Air-Gap Cloud Gate (checked BEFORE semantic escalation when cloud is requested).
            if cloud_synthesis_requested:
                if slice_obj.contains_personal_vault_data or slice_obj.privacy_tier != "sanitized":
                    air_gap_blocks += 1
                    msg = (
                        "Air-gap violation: personal_vault.db or air-gapped DataSlice "
                        "cannot be sent to LeavesCloudAgent."
                    )
                    if self.config.strict_raise_on_cloud_taint:
                        raise PermissionError(msg)
                    results.append(
                        SliceExecutionResult(
                            slice_id=slice_obj.slice_id,
                            tag=slice_obj.tag,
                            execution_tier="air_gap_blocked",
                            weight_wi=weight_wi,
                            should_prune=should_prune,
                            air_gap_blocked=True,
                            llm_tokens_used=0,
                            latency_ms=(time.perf_counter() - t_slice_start) * 1000.0,
                            error=msg,
                        )
                    )
                    continue

                if self.config.allow_cloud_synthesis:
                    leaves_req = SanitizedCloudRequest(
                        request_id=slice_obj.slice_id,
                        prompt=slice_obj.raw_payload,
                        sanitized_context=[slice_obj.title] if slice_obj.title else [],
                        contains_personal_vault_data=False,
                        air_gap_cleared_by="nested_model_orchestrator",
                    )
                    cloud_out = await self._get_leaves_agent().synthesize(leaves_req)
                    cloud_calls += 1
                    results.append(
                        SliceExecutionResult(
                            slice_id=slice_obj.slice_id,
                            tag=slice_obj.tag,
                            execution_tier="leaves_cloud",
                            weight_wi=weight_wi,
                            should_prune=should_prune,
                            cloud_output=cloud_out,
                            air_gap_blocked=False,
                            llm_tokens_used=slice_obj.estimated_tokens,
                            latency_ms=(time.perf_counter() - t_slice_start) * 1000.0,
                        )
                    )
                    continue

            # Tier 3: Semantic micro-inference via NestedCallableLightAgent (isolated slice only).
            semantic_needed = (
                slice_obj.tag == TagType.SEMANTIC_MICRO
                or prediction.semantic_escalation_score >= self.config.semantic_escalation_threshold
            )
            if semantic_needed:
                nano_agent = self._get_nano_agent()
                nano_req = NanoSliceInferenceInput(
                    slice=slice_obj,
                    instruction=slice_obj.title or f"Process isolated {slice_obj.tag.value} slice.",
                    micro_hint=prediction,
                )
                nano_out = await nano_agent.infer_slice(nano_req)
                nano_calls += 1
                results.append(
                    SliceExecutionResult(
                        slice_id=slice_obj.slice_id,
                        tag=slice_obj.tag,
                        execution_tier="nano_local_llm",
                        weight_wi=weight_wi,
                        should_prune=should_prune,
                        nano_output=nano_out,
                        air_gap_blocked=slice_obj.contains_personal_vault_data,
                        llm_tokens_used=slice_obj.estimated_tokens,
                        latency_ms=(time.perf_counter() - t_slice_start) * 1000.0,
                    )
                )
                continue

            # Tier 4: Local Twigs fallback on the isolated DataSlice.
            twigs = self._get_twigs_executor()
            twig_out = await twigs.execute(
                TwigTaskInput(
                    task_id=slice_obj.slice_id,
                    instruction=slice_obj.title or f"Execute local {slice_obj.tag.value} task.",
                    context_items=[slice_obj.raw_payload],
                    domain_tag=slice_obj.tag.value,
                )
            )
            nano_calls += 1
            results.append(
                SliceExecutionResult(
                    slice_id=slice_obj.slice_id,
                    tag=slice_obj.tag,
                    execution_tier="twigs_local_llm",
                    weight_wi=weight_wi,
                    should_prune=should_prune,
                    deterministic_output=twig_out,
                    air_gap_blocked=slice_obj.contains_personal_vault_data,
                    llm_tokens_used=slice_obj.estimated_tokens,
                    latency_ms=(time.perf_counter() - t_slice_start) * 1000.0,
                )
            )

        return OrchestratorExecutionReport(
            bundle_id=bundle.bundle_id,
            total_slices=len(bundle.slices),
            deterministic_hits=det_hits,
            nano_llm_calls=nano_calls,
            cloud_calls=cloud_calls,
            air_gap_blocks=air_gap_blocks,
            token_savings_ratio=bundle.token_savings_ratio,
            results=results,
            total_latency_ms=(time.perf_counter() - t_bundle_start) * 1000.0,
        )

    async def process_prompt(
        self,
        raw_text: str,
        source_id: str = "prompt",
        from_personal_vault: bool = True,
        local_references: list[ReferenceEntry] | None = None,
        cloud_synthesis_requested: bool = False,
    ) -> OrchestratorExecutionReport:
        """Pre-group a raw prompt into isolated slices and execute the nested cascade."""
        bundle = pre_group_prompt(
            raw_text=raw_text,
            source_id=source_id,
            from_personal_vault=from_personal_vault,
            micro_model=self.micro_model,
        )
        return await self.process_bundle(
            bundle=bundle,
            local_references=local_references,
            cloud_synthesis_requested=cloud_synthesis_requested,
        )
