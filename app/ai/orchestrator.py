"""AI orkestrasyonu.

Akis statik iki katmanli bir DAG:

    N donem analizi (paralel, bagimsiz)  ->  1 yonetici sentezi

Dongusu, kosullu dallanmasi, insan onayi adimi ve uzun sureli resume
ihtiyaci olmadigi icin bir orkestrasyon framework'u (LangGraph/LangChain)
kullanmiyoruz -- karsiligi `asyncio.gather` + bir semafor. Boylece SDK'nin
structured outputs ve prompt caching ozelliklerine dogrudan erisimimizi
koruyoruz; ikisi de bu projede kritik.

Framework'un verecegi degerli parcalar (akisin acikca gorunmesi, telemetri,
yeniden deneme) burada elle ve ~150 satirda saglanmistir.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai import context as ctx_builder
from app.ai.ai_schemas import ExecutiveSummary, PeriodAnalysis, QAAnswer
from app.ai.client import LLMClient
from app.ai.telemetry import RunStats
from app.ai.validation import FactIndex, GroundingReport, collect_evidence, verify
from app.core.errors import AIError
from app.domain.models import AnalyticsResult, QualityReport
from app.domain.packs.base import DatasetPack

_log = logging.getLogger("app.ai.orchestrator")


@dataclass(slots=True)
class AnalysisBundle:
    """Bir analiz kosusunun tam ciktisi."""

    periods: list[PeriodAnalysis]
    summary: ExecutiveSummary | None
    grounding: GroundingReport
    stats: RunStats
    failed_periods: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "periods": [p.model_dump() for p in self.periods],
            "summary": self.summary.model_dump() if self.summary else None,
            "grounding": self.grounding.to_dict(),
            "telemetry": self.stats.to_dict(),
            "failed_periods": self.failed_periods,
        }


class AnalysisOrchestrator:
    """Donem analizlerini ve yonetici sentezini uretir."""

    def __init__(self, client: LLMClient, *, max_concurrency: int = 6) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def run(
        self,
        result: AnalyticsResult,
        pack: DatasetPack,
        quality: QualityReport | None = None,
    ) -> AnalysisBundle:
        system = ctx_builder.build_system_prompt(pack)
        shared = ctx_builder.build_shared_context(result, pack, quality)
        stats = RunStats()

        # --- 1. katman: donemler ---------------------------------------------
        # Onemli detay: ilk cagriyi TEK BASINA bekliyoruz, sonra kalanlari
        # paralel saliyoruz.
        #
        # Sebep: bir onbellek girdisi ancak onu yazan istegin yaniti akmaya
        # basladiktan sonra okunabilir hale gelir. Yedi cagriyi ayni anda
        # salarsak hicbiri digerinin yazdigini okuyamaz; yedisi de ayni buyuk
        # baglami yazar ve yazma ucreti (~1.25x giris) yedi kez odenir.
        # Olculdu: bu sirali-once yaklasimi ayni analizin maliyetini
        # $0.40'tan $0.22'ye indiriyor (%44). Duvar saati neredeyse ayni,
        # cunku onbellekten okuyan cagrilar daha hizli isleniyor.
        deltas = {d.period: d for d in result.deltas}

        head, *rest = result.periods
        first = await self._safe_period(head, deltas.get(head), result, pack, system, shared)
        remaining = await asyncio.gather(
            *(
                self._analyze_period(period, deltas.get(period), result, pack, system, shared)
                for period in rest
            ),
            return_exceptions=True,
        )
        outcomes = [first, *remaining]

        periods: list[PeriodAnalysis] = []
        failed: list[dict[str, str]] = []
        for period, outcome in zip(result.periods, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                _log.warning(
                    "Donem analizi basarisiz",
                    extra={"period": period, "error": str(outcome)},
                )
                failed.append({"period": period, "error": str(outcome)})
                continue
            analysis, call_stats = outcome
            stats.add(call_stats)
            periods.append(analysis)

        if not periods:
            raise AIError(
                "Hicbir donem icin analiz uretilemedi.",
                details={"failed_periods": failed},
            )

        # --- 2. katman: yonetici sentezi -------------------------------------
        summary: ExecutiveSummary | None = None
        try:
            summary, summary_stats = await self._summarize(periods, pack, system, shared)
            stats.add(summary_stats)
        except Exception as exc:
            _log.warning("Yonetici ozeti uretilemedi", extra={"error": str(exc)})
            failed.append({"period": "ozet", "error": str(exc)})

        # --- dogrulama: her kanit hesaplanmis veriye baglaniyor mu? -----------
        index = FactIndex(result, pack)
        payload: list[Any] = [*periods]
        if summary is not None:
            payload.append(summary)
        grounding = verify(collect_evidence(payload), index)

        _log.info(
            "ai_run_complete",
            extra={
                "periods": len(periods),
                "failed": len(failed),
                "grounding_ratio": round(grounding.ratio, 4),
                **stats.to_dict(),
            },
        )
        return AnalysisBundle(periods, summary, grounding, stats, failed)

    # -- tekil cagrilar ---------------------------------------------------
    async def _safe_period(self, *args, **kwargs):
        """Ilk cagri: hata firlatmak yerine dondurur.

        asyncio.gather(return_exceptions=True) davranisini tek cagri icin de
        saglar; boylece asagidaki dongude tek tip islem yapilir.
        """
        try:
            return await self._analyze_period(*args, **kwargs)
        except BaseException as exc:
            return exc

    async def _analyze_period(
        self,
        period: str,
        delta: Any,
        result: AnalyticsResult,
        pack: DatasetPack,
        system: str,
        shared: str,
    ) -> tuple[PeriodAnalysis, Any]:
        question = ctx_builder.build_period_question(period, delta, result, pack)
        async with self._semaphore:
            return await self._client.structured(
                label=f"period:{period}",
                system=system,
                cached_context=shared,
                question=question,
                schema=PeriodAnalysis,
            )

    async def _summarize(
        self,
        periods: list[PeriodAnalysis],
        pack: DatasetPack,
        system: str,
        shared: str,
    ) -> tuple[ExecutiveSummary, Any]:
        question = ctx_builder.build_summary_question(periods, pack)
        async with self._semaphore:
            return await self._client.structured(
                label="executive_summary",
                system=system,
                cached_context=shared,
                question=question,
                schema=ExecutiveSummary,
            )


class QAOrchestrator:
    """Veri uzerinde serbest soru-cevap (bonus).

    Text-to-SQL yapmiyoruz: model sorgu yazmaz, hesaplanmis tablolari yorumlar.
    Boylece "AI sayi hesaplamaz" kurali soru-cevapta da bozulmuyor.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def ask(
        self,
        question: str,
        result: AnalyticsResult,
        pack: DatasetPack,
        quality: QualityReport | None = None,
    ) -> tuple[QAAnswer, GroundingReport, RunStats]:
        system = ctx_builder.build_system_prompt(pack)
        shared = ctx_builder.build_shared_context(result, pack, quality)

        answer, call_stats = await self._client.structured(
            label="qa",
            system=system,
            cached_context=shared,
            question=ctx_builder.build_qa_question(question),
            schema=QAAnswer,
        )

        stats = RunStats()
        stats.add(call_stats)
        grounding = verify(collect_evidence(answer), FactIndex(result, pack))
        return answer, grounding, stats
