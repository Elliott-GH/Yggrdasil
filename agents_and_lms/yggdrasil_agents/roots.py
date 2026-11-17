"""Roots layer: local-only ingestion and normalization micro-agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .local_engine import LocalEngine

PrivacyTier = Literal["air_gapped", "sanitized"]


class RootContextItem(BaseModel):
    """Normalized atomic context item extracted by the Roots agent."""

    item_id: str
    title: str
    summary: str
    domain_tags: list[str] = Field(default_factory=list)
    contains_personal_vault_data: bool = True
    privacy_tier: PrivacyTier = "air_gapped"


class RootIngestionInput(BaseModel):
    """Input payload for local Roots ingestion."""

    source_id: str
    raw_text: str = Field(min_length=1)
    from_personal_vault: bool = True


class RootIngestionOutput(BaseModel):
    """Structured output returned by RootsAgent."""

    source_id: str
    items: list[RootContextItem] = Field(default_factory=list)
    privacy_tier: PrivacyTier = "air_gapped"
    notes: str = ""


class RootsAgent:
    """Single-responsibility local ingestion micro-agent using the shared LocalEngine."""

    SYSTEM_INSTRUCTIONS = (
        "You are the Yggdrasil Roots ingestion micro-agent. "
        "Extract structured atomic context items from raw local input. "
        "Never fabricate external facts and preserve privacy classifications."
    )

    def __init__(self, engine: LocalEngine | None = None) -> None:
        self.engine: LocalEngine = engine or LocalEngine.get_shared()
        self._agent = self.engine.create_micro_agent(
            output_type=RootIngestionOutput,
            instructions=self.SYSTEM_INSTRUCTIONS,
            name="yggdrasil-roots",
        )

    async def ingest(self, payload: RootIngestionInput) -> RootIngestionOutput:
        """Run local Roots extraction and enforce vault privacy defaults."""
        result = await self._agent.run(
            f"Source ID: {payload.source_id}\n"
            f"From Personal Vault: {payload.from_personal_vault}\n\n"
            f"{payload.raw_text}"
        )
        output = result.output
        if payload.from_personal_vault:
            output.privacy_tier = "air_gapped"
            for item in output.items:
                item.contains_personal_vault_data = True
                item.privacy_tier = "air_gapped"
        return output
