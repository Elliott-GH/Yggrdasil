"""Single shared local LLM engine manager for Ollama and LM Studio endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, TypeVar, cast

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)
LocalProviderType = Literal["ollama", "lm_studio"]


class LocalEngineConfig(BaseModel):
    """Configuration for the single resident local LLM instance."""

    provider: LocalProviderType = "ollama"
    ollama_base_url: str = "http://localhost:11434/v1"
    lm_studio_base_url: str = "http://localhost:1234/v1"
    model_name: str = "qwen2.5:14b"
    api_key: str = "api-key-not-set"
    timeout_seconds: float = Field(default=120.0, gt=0.0)

    @property
    def active_base_url(self) -> str:
        """Return the base URL corresponding to the configured local provider."""
        if self.provider == "ollama":
            return self.ollama_base_url
        return self.lm_studio_base_url


class LocalEngineStatus(BaseModel):
    """Healthcheck result from probing the resident local inference server."""

    provider: LocalProviderType
    base_url: str
    model_name: str
    reachable: bool
    available_models: list[str] = Field(default_factory=list)
    error: str | None = None


class LocalEngine:
    """Singleton manager ensuring all local micro-agents share one VRAM model instance."""

    _instance: LocalEngine | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, config: LocalEngineConfig | None = None) -> None:
        self.config: LocalEngineConfig = config or LocalEngineConfig()
        self._http_client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=self.config.timeout_seconds
        )
        self._openai_client: AsyncOpenAI = AsyncOpenAI(
            base_url=self.config.active_base_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout_seconds,
        )

    @classmethod
    def get_shared(cls, config: LocalEngineConfig | None = None) -> LocalEngine:
        """Return the single shared LocalEngine instance, enforcing single-VRAM residency."""
        if cls._instance is None:
            cls._instance = cls(config=config)
        elif config is not None and config != cls._instance.config:
            raise RuntimeError(
                "LocalEngine already initialized with a different resident model configuration. "
                "Close the existing instance before switching models to prevent VRAM contention."
            )
        return cls._instance

    @classmethod
    async def reset_shared(cls) -> None:
        """Close and release the shared engine instance."""
        async with cls._lock:
            if cls._instance is not None:
                await cls._instance.aclose()
                cls._instance = None

    def build_model(self) -> OllamaModel | OpenAIChatModel:
        """Construct a pydantic-ai model bound to the shared AsyncOpenAI client."""
        if self.config.provider == "ollama":
            return OllamaModel(
                model_name=self.config.model_name,
                provider=OllamaProvider(openai_client=self._openai_client),
            )
        return OpenAIChatModel(
            model_name=self.config.model_name,
            provider=OpenAIProvider(openai_client=self._openai_client),
        )

    def create_micro_agent(
        self,
        output_type: type[OutputModelT],
        instructions: str,
        name: str | None = None,
    ) -> Agent[None, OutputModelT]:
        """Create a single-responsibility pydantic-ai Agent using the shared resident model."""
        resolved_output: type[OutputModelT] | NativeOutput[OutputModelT] = (
            NativeOutput(output_type) if self.config.provider == "ollama" else output_type
        )
        return Agent(
            model=self.build_model(),
            output_type=resolved_output,
            instructions=instructions,
            name=name,
        )

    async def healthcheck(self) -> LocalEngineStatus:
        """Probe the local OpenAI-compatible `/models` endpoint asynchronously."""
        models_url = f"{self.config.active_base_url.rstrip('/')}/models"
        try:
            response = await self._http_client.get(models_url)
            response.raise_for_status()
            payload = response.json()
            raw_items = payload.get("data", []) if isinstance(payload, dict) else []
            model_ids = [
                str(item["id"])
                for item in raw_items
                if isinstance(item, dict) and "id" in item
            ]
            return LocalEngineStatus(
                provider=self.config.provider,
                base_url=self.config.active_base_url,
                model_name=self.config.model_name,
                reachable=True,
                available_models=model_ids,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return LocalEngineStatus(
                provider=self.config.provider,
                base_url=self.config.active_base_url,
                model_name=self.config.model_name,
                reachable=False,
                error=str(exc),
            )

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model_name: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream conversational chat tokens from the shared resident local LLM."""
        resolved_model = model_name or self.config.model_name
        stream = await self._openai_client.chat.completions.create(
            model=resolved_model,
            messages=cast(Any, messages),
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    yield content

    async def aclose(self) -> None:
        """Close underlying async HTTP and OpenAI transport clients."""
        await self._openai_client.close()
        await self._http_client.aclose()
