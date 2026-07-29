"""AI analiz kullanim senaryolari.

Onbellek burada yonetilir. Anahtar: dosya icerigi + pack + prompt surumu +
model + cagri tipi. Model anahtara dahil, cunku Sonnet ile uretilmis bir
analizi Opus'a gecince servis etmek yaniltici olur; prompt surumu de dahil,
cunku prompt degistiginde eski cikti gecersizdir.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.ai.client import AnthropicClient, LLMClient
from app.ai.orchestrator import AnalysisOrchestrator, QAOrchestrator
from app.core.config import Settings
from app.core.errors import AINotConfiguredError
from app.services.dataset_service import LoadedDataset
from app.storage.repositories import AICacheRepository

_log = logging.getLogger(__name__)


def build_llm_client(settings: Settings) -> LLMClient:
    if not settings.ai_configured:
        raise AINotConfiguredError()
    return AnthropicClient(settings)


class AnalysisService:
    def __init__(
        self,
        cache: AICacheRepository,
        settings: Settings,
        client_factory=build_llm_client,
    ) -> None:
        self._cache = cache
        self._settings = settings
        self._client_factory = client_factory

    # -- tam analiz --------------------------------------------------------
    async def analyze(self, loaded: LoadedDataset, *, refresh: bool = False) -> dict[str, Any]:
        key = self._cache_key(loaded, kind="analysis")

        if not refresh and self._settings.ai_cache_enabled:
            cached = await self._cache.get(key)
            if cached is not None:
                _log.info(
                    "ai_cache_hit",
                    extra={"dataset_id": loaded.record.id, "kind": "analysis"},
                )
                return {**cached, "cached": True}

        client = self._client_factory(self._settings)
        orchestrator = AnalysisOrchestrator(
            client, max_concurrency=self._settings.ai_max_concurrency
        )
        bundle = await orchestrator.run(loaded.analytics, loaded.pack, loaded.quality)
        payload = {**bundle.to_dict(), "model": self._settings.ai_model, "cached": False}

        if self._settings.ai_cache_enabled:
            await self._cache.put(
                cache_key=key,
                dataset_id=loaded.record.id,
                kind="analysis",
                payload=payload,
                grounding_ratio=bundle.grounding.ratio,
                cost_usd=bundle.stats.total_cost_usd,
            )
        return payload

    async def is_cached(self, loaded: LoadedDataset) -> bool:
        if not self._settings.ai_cache_enabled:
            return False
        return await self._cache.get(self._cache_key(loaded, kind="analysis")) is not None

    # -- soru-cevap --------------------------------------------------------
    async def ask(self, loaded: LoadedDataset, question: str) -> dict[str, Any]:
        key = self._cache_key(loaded, kind="qa", extra=question.strip().casefold())

        if self._settings.ai_cache_enabled:
            cached = await self._cache.get(key)
            if cached is not None:
                return {**cached, "cached": True}

        client = self._client_factory(self._settings)
        answer, grounding, stats = await QAOrchestrator(client).ask(
            question, loaded.analytics, loaded.pack, loaded.quality
        )
        payload = {
            "answer": answer.model_dump(),
            "grounding": grounding.to_dict(),
            "telemetry": stats.to_dict(),
            "cached": False,
        }
        if self._settings.ai_cache_enabled:
            await self._cache.put(
                cache_key=key,
                dataset_id=loaded.record.id,
                kind="qa",
                payload=payload,
                grounding_ratio=grounding.ratio,
                cost_usd=stats.total_cost_usd,
            )
        return payload

    async def invalidate(self, dataset_id: str) -> None:
        await self._cache.invalidate_dataset(dataset_id)

    # ---------------------------------------------------------------------
    def _cache_key(self, loaded: LoadedDataset, *, kind: str, extra: str = "") -> str:
        parts = "|".join(
            [
                loaded.record.content_hash,
                loaded.pack.key,
                self._settings.prompt_version,
                self._settings.ai_model,
                self._settings.ai_effort,
                kind,
                extra,
            ]
        )
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:64]
