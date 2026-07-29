"""LLM istemcisi: Protocol + Anthropic adaptoru.

Protocol'u burada kullaniyoruz cunku bu gercekten *takas edilebilir davranis*:
testlerde sahte istemci, ileride baska bir saglayici veya bir orkestrasyon
katmani ayni arayuzun arkasina takilabilir. Servis ve domain katmanlari
Anthropic'i hic gormez.

Iki ozellik bilerek adaptorun icinde:

1) Structured outputs -- `messages.parse(output_format=PydanticModel)`.
   Sema API katmaninda zorlanir; donen deger dogrudan tipli nesnedir.
   "Bazen duzgun JSON dondu bazen donmedi" problemi hic dogmaz.

2) Prompt caching -- sistem promptu ve buyuk baglam blogu `cache_control`
   ile isaretlenir. Alti donem analizi ayni baglami paylastigi icin ilki
   yazar, kalani ~%10 fiyata okur.
"""

from __future__ import annotations

import time
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.ai.telemetry import CallStats
from app.core.config import Settings
from app.core.errors import (
    AIError,
    AINotConfiguredError,
    AIRateLimitedError,
    AIRefusedError,
    AIResponseInvalidError,
)

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    """Yapilandirilmis cikti ureten dil modeli istemcisi."""

    async def structured(
        self,
        *,
        label: str,
        system: str,
        cached_context: str,
        question: str,
        schema: type[T],
    ) -> tuple[T, CallStats]:
        """Semaya uygun bir nesne ve cagri istatistiklerini doner.

        `cached_context` cagrilar arasinda degismeyen buyuk blok; onbelleklenir.
        `question` cagriya ozgu, degisen kisim; onbellek kirilma noktasindan sonra gelir.
        """
        ...


class AnthropicClient:
    """Claude API adaptoru."""

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_configured:
            raise AINotConfiguredError()
        self._settings = settings
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,  # 429/5xx icin SDK'nin kendi backoff'u
        )

    async def structured(
        self,
        *,
        label: str,
        system: str,
        cached_context: str,
        question: str,
        schema: type[T],
    ) -> tuple[T, CallStats]:
        settings = self._settings
        stats = CallStats(label=label, model=settings.ai_model)
        started = time.perf_counter()

        # Onbellek dizilimi: [sistem][baglam] sabit prefix, [soru] degisken sonek.
        # cache_control son sabit blogun uzerinde durur.
        system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        content = [
            {"type": "text", "text": cached_context, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": question},
        ]

        last_error: Exception | None = None
        for attempt in range(1, 3):
            stats.attempts = attempt
            try:
                response = await self._client.messages.parse(
                    model=settings.ai_model,
                    max_tokens=settings.ai_max_tokens,
                    system=system_blocks,
                    messages=[{"role": "user", "content": content}],
                    output_format=schema,
                    output_config={"effort": settings.ai_effort},
                )
            except anthropic.RateLimitError as exc:
                raise AIRateLimitedError(details={"label": label}) from exc
            except anthropic.APIStatusError as exc:
                raise AIError(
                    f"Claude API hatasi ({exc.status_code}).", details={"label": label}
                ) from exc
            except anthropic.APIConnectionError as exc:
                raise AIError("Claude API'ye baglanilamadi.", details={"label": label}) from exc
            except ValidationError as exc:
                # Sema uymadi: bir kez daha dene, hatayi modele geri bildir.
                last_error = exc
                content = [
                    *content[:2],
                    {
                        "type": "text",
                        "text": (
                            "Onceki yanitin beklenen semaya uymadi. Hata:\n"
                            f"{exc}\n\nSemaya birebir uyan bir yanit uret."
                        ),
                    },
                ]
                continue

            _apply_usage(stats, response)
            stats.duration_ms = int((time.perf_counter() - started) * 1000)

            if getattr(response, "stop_reason", None) == "refusal":
                raise AIRefusedError(details={"label": label})

            parsed = response.parsed_output
            if parsed is None:
                last_error = AIResponseInvalidError("Model bos yanit dondu.")
                continue
            return parsed, stats

        stats.duration_ms = int((time.perf_counter() - started) * 1000)
        raise AIResponseInvalidError(
            "Model iki denemede de semaya uygun yanit uretemedi.",
            details={"label": label, "error": str(last_error)},
        )


def _apply_usage(stats: CallStats, response: object) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    stats.input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    stats.output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    stats.cache_write_tokens = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    stats.cache_read_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
