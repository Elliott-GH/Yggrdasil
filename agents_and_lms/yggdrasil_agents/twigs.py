"""Twigs layer: single-responsibility local micro-agents sharing LocalEngine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .local_engine import LocalEngine


class TwigTaskInput(BaseModel):
    """Typed input for a local single-responsibility micro-agent task."""

    task_id: str
    instruction: str = Field(min_length=1)
    context_items: list[str] = Field(default_factory=list)
    domain_tag: str = "general"


class TwigTaskOutput(BaseModel):
    """Strictly validated Pydantic output returned by TwigsExecutor."""

    task_id: str
    result_summary: str
    structured_findings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    executed_locally: Literal[True] = True


class TwigsExecutor:
    """Executes single-responsibility local tasks on the shared resident model."""

    SYSTEM_INSTRUCTIONS = (
        "You are a focused Yggdrasil Twig micro-agent operating strictly locally. "
        "Solve the single assigned sub-task concisely and return structured findings."
    )

    def __init__(self, engine: LocalEngine | None = None) -> None:
        self.engine: LocalEngine = engine or LocalEngine.get_shared()
        self._agent = self.engine.create_micro_agent(
            output_type=TwigTaskOutput,
            instructions=self.SYSTEM_INSTRUCTIONS,
            name="yggdrasil-twigs",
        )

    async def execute(self, payload: TwigTaskInput) -> TwigTaskOutput:
        """Execute a single local micro-agent task and validate Pydantic output."""
        joined_context = "\n".join(f"- {item}" for item in payload.context_items)
        prompt = (
            f"Task ID: {payload.task_id}\n"
            f"Domain: {payload.domain_tag}\n"
            f"Instruction: {payload.instruction}\n\n"
            f"Local Context:\n{joined_context}"
        )
        result = await self._agent.run(prompt)
        return result.output
