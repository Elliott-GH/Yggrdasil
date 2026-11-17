"""Leaves layer: Gemini cloud synthesis with strict runtime air-gap enforcement."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


class SanitizedCloudRequest(BaseModel):
    """Air-gap-cleared request schema eligible for cloud Gemini synthesis."""

    request_id: str
    prompt: str = Field(min_length=1)
    sanitized_context: list[str] = Field(default_factory=list)
    contains_personal_vault_data: Literal[False] = False
    air_gap_cleared_by: str = "trunk_router"


class LeafCloudSynthesis(BaseModel):
    """Structured cloud synthesis output from Gemini."""

    request_id: str
    model_name: str
    synthesis: str
    key_insights: list[str] = Field(default_factory=list)
    cloud_executed: Literal[True] = True


def _assert_air_gap_cleared(payload: Any) -> SanitizedCloudRequest:
    """Reject any payload that is not explicitly verified as free of personal_vault.db data."""
    if not isinstance(payload, SanitizedCloudRequest):
        raise PermissionError(
            "Air-gap violation: LeavesCloudAgent accepts only SanitizedCloudRequest instances."
        )
    if payload.contains_personal_vault_data is not False:
        raise PermissionError(
            "Air-gap violation: personal_vault.db context is prohibited in cloud Gemini calls."
        )
    return payload


class LeavesCloudAgent:
    """Cloud Gemini synthesis wrapper enforcing strict air-gap privacy verification."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash",
    ) -> None:
        self.model_name: str = model_name
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        self._client: genai.Client | None = (
            genai.Client(api_key=resolved_key) if resolved_key else None
        )

    async def synthesize(self, payload: SanitizedCloudRequest) -> LeafCloudSynthesis:
        """Synthesize sanitized public/domain prompts via Gemini `client.aio.models`."""
        cleared = _assert_air_gap_cleared(payload)
        if self._client is None:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured; cannot execute cloud Leaves synthesis."
            )

        context_block = "\n".join(f"- {item}" for item in cleared.sanitized_context)
        contents = (
            f"Request ID: {cleared.request_id}\n"
            f"Prompt: {cleared.prompt}\n\n"
            f"Sanitized Context:\n{context_block}"
        )
        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LeafCloudSynthesis,
            ),
        )
        parsed = response.parsed
        if not isinstance(parsed, LeafCloudSynthesis):
            return LeafCloudSynthesis.model_validate(parsed)
        return parsed

    async def stream_chat(
        self,
        payload: SanitizedCloudRequest,
        history: Sequence[Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream plain-text conversational response from Gemini after strict air-gap verification."""
        cleared = _assert_air_gap_cleared(payload)
        if self._client is None:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured; cannot execute cloud Leaves chat stream."
            )

        sections: list[str] = []
        if cleared.sanitized_context:
            context_block = "\n".join(f"- {item}" for item in cleared.sanitized_context)
            sections.append(f"Context:\n{context_block}")

        if history:
            history_lines: list[str] = []
            for msg in history:
                role = getattr(msg, "role", None) or (
                    msg.get("role") if isinstance(msg, dict) else "user"
                )
                content = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else str(msg)
                )
                if content:
                    history_lines.append(f"{str(role).upper()}: {content}")
            if history_lines:
                sections.append("Conversation History:\n" + "\n".join(history_lines))

        sections.append(f"USER: {cleared.prompt}")
        contents = "\n\n".join(sections)

        response_stream = await self._client.aio.models.generate_content_stream(
            model=self.model_name,
            contents=contents,
        )
        async for chunk in response_stream:
            text_piece = getattr(chunk, "text", None)
            if isinstance(text_piece, str) and text_piece:
                yield text_piece
