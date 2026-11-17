"""Callable single-slice nano LLM wrapper bound to the shared LocalEngine (SPEC-001)."""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from .local_engine import LocalEngine, LocalEngineConfig
from .micro_model import MicroModelPrediction
from .pre_slicer import DataSlice
from .roots import PrivacyTier


class NanoSliceInferenceInput(BaseModel):
    """Strictly scoped single-slice inference request for NestedCallableLightAgent."""

    slice: DataSlice
    instruction: str = Field(min_length=1, max_length=512)
    micro_hint: MicroModelPrediction | None = None
    deterministic_context: str | None = Field(default=None, max_length=2048)
    max_output_chars: int = Field(default=1024, ge=64, le=4096)


class NanoSliceInferenceOutput(BaseModel):
    """Validated structured output returned by NestedCallableLightAgent."""

    slice_id: str
    model_name: str
    concise_answer: str
    extracted_facts: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    requires_cloud_synthesis: bool = False
    executed_locally: Literal[True] = True
    privacy_tier: PrivacyTier = "air_gapped"
    latency_ms: float = Field(default=0.0, ge=0.0)


class NestedCallableLightAgent:
    """Single-slice nano LLM micro-agent bound strictly to LocalEngine.get_shared()."""

    SYSTEM_INSTRUCTIONS = (
        "You are yggdrasil-nano, an isolated single-slice local micro-agent. "
        "Operate strictly on the single pre-grouped DataSlice provided in the prompt. "
        "Never invent citations, DOIs, physical constants, or external facts. "
        "Preserve all air-gap privacy flags and numerical units verbatim."
    )

    def __init__(
        self,
        engine: LocalEngine | None = None,
        config: LocalEngineConfig | None = None,
    ) -> None:
        self.engine: LocalEngine = engine or LocalEngine.get_shared(config=config)
        self._agent: Agent[None, NanoSliceInferenceOutput] = self.engine.create_micro_agent(
            output_type=NanoSliceInferenceOutput,
            instructions=self.SYSTEM_INSTRUCTIONS,
            name="yggdrasil-nano",
        )

    def _build_slice_prompt(self, request: NanoSliceInferenceInput) -> str:
        """Build a token-conserving prompt containing ONLY the single isolated DataSlice."""
        target_slice = request.slice
        sections: list[str] = [
            f"Slice ID: {target_slice.slice_id}",
            f"Tag: {target_slice.tag.value}",
            f"Privacy Tier: {target_slice.privacy_tier}",
            f"Max Output Chars: {request.max_output_chars}",
            f"Instruction: {request.instruction}",
        ]
        if target_slice.title:
            sections.append(f"Slice Title: {target_slice.title}")
        if target_slice.structured_kv:
            kv_pairs = ", ".join(f"{k}={v}" for k, v in target_slice.structured_kv.items())
            sections.append(f"Structured Header KV: {kv_pairs}")
        if request.micro_hint is not None:
            sections.append(
                "Micro-Scorer Hint: "
                f"predicted_tag={request.micro_hint.predicted_tag.value}, "
                f"deterministic_score={request.micro_hint.deterministic_score:.3f}, "
                f"semantic_escalation_score={request.micro_hint.semantic_escalation_score:.3f}"
            )
        if request.deterministic_context:
            sections.append(f"Deterministic Tool Context:\n{request.deterministic_context}")
        sections.append(f"Isolated Slice Payload:\n{target_slice.raw_payload}")
        return "\n".join(sections)

    async def infer_slice(self, request: NanoSliceInferenceInput) -> NanoSliceInferenceOutput:
        """Execute local nano inference strictly over a single isolated DataSlice."""
        prompt = self._build_slice_prompt(request)
        t_start = time.perf_counter()
        result = await self._agent.run(prompt)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        output = result.output
        output.slice_id = request.slice.slice_id
        output.model_name = self.engine.config.model_name
        output.privacy_tier = request.slice.privacy_tier
        output.latency_ms = elapsed_ms

        if len(output.concise_answer) > request.max_output_chars:
            output.concise_answer = output.concise_answer[: request.max_output_chars]

        # Mandatory post-execution air-gap taint clamp (SPEC-001 Section 4.2).
        if request.slice.contains_personal_vault_data or request.slice.privacy_tier == "air_gapped":
            output.privacy_tier = "air_gapped"
            output.requires_cloud_synthesis = False

        return output

    async def __call__(self, request: NanoSliceInferenceInput) -> NanoSliceInferenceOutput:
        """Allow direct async invocation `await nano_agent(request)`."""
        return await self.infer_slice(request)
