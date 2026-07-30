"""AI analiz ve soru-cevap uclari."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import AnalysisServiceDep, LoadedDatasetDep, SettingsDep
from app.api.responses import AI_ERRORS
from app.schemas.analysis import (
    AnalysisResponse,
    AnalysisStatusResponse,
    AskRequest,
    AskResponse,
)

router = APIRouter(prefix="/datasets/{dataset_id}", tags=["analysis"], responses=AI_ERRORS)


@router.get(
    "/analysis/status",
    response_model=AnalysisStatusResponse,
    summary="Analiz hazır mı, kaç çağrı gerekecek",
    description=(
        "Frontend'in 'analiz üret' butonunu maliyet uyarısıyla göstermesi için. "
        "Önbellekte varsa çağrı yapılmayacağını bildirir."
    ),
)
async def analysis_status(
    dataset_id: str,
    loaded: LoadedDatasetDep,
    service: AnalysisServiceDep,
    settings: SettingsDep,
) -> AnalysisStatusResponse:
    cached = await service.is_cached(loaded)
    return AnalysisStatusResponse(
        dataset_id=dataset_id,
        ai_configured=settings.ai_configured,
        cached=cached,
        model=settings.ai_model,
        effort=settings.ai_effort,
        estimated_calls=0 if cached else len(loaded.analytics.periods) + 1,
        detail={
            "periods": list(loaded.analytics.periods),
            "risk_count": len(loaded.analytics.risks),
        },
    )


@router.post(
    "/analysis",
    response_model=AnalysisResponse,
    summary="Dönemsel analiz + yönetici özeti üret",
    description=(
        "Her dönem için paralel bir AI çağrısı, ardından tek bir sentez çağrısı. "
        "Sonuç önbelleğe yazılır; aynı veri seti için tekrar çağrıldığında AI'a "
        "gidilmez. `refresh=true` ile yeniden üretilebilir."
    ),
)
async def create_analysis(
    dataset_id: str,
    loaded: LoadedDatasetDep,
    service: AnalysisServiceDep,
    settings: SettingsDep,
    refresh: bool = Query(False, description="Önbelleği yok say ve yeniden üret"),
) -> AnalysisResponse:
    payload = await service.analyze(loaded, refresh=refresh)
    return AnalysisResponse(
        dataset_id=dataset_id,
        pack_key=loaded.pack.key,
        model=payload.get("model", settings.ai_model),
        cached=bool(payload.get("cached")),
        cached_at=payload.get("_cached_at"),
        periods=payload["periods"],
        summary=payload.get("summary"),
        grounding=payload["grounding"],
        telemetry=payload["telemetry"],
        failed_periods=payload.get("failed_periods", []),
    )


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Veri üzerinde serbest soru-cevap",
    description=(
        "Model SQL yazmaz: hesaplanmış tabloları yorumlar. Böylece 'AI sayı "
        "hesaplamaz' kuralı soru-cevapta da korunur ve her yanıt kanıt taşır."
    ),
)
async def ask(
    dataset_id: str,
    body: AskRequest,
    loaded: LoadedDatasetDep,
    service: AnalysisServiceDep,
) -> AskResponse:
    payload = await service.ask(loaded, body.question)
    return AskResponse(
        dataset_id=dataset_id,
        question=body.question,
        answer=payload["answer"],
        grounding=payload["grounding"],
        telemetry=payload["telemetry"],
        cached=bool(payload.get("cached")),
    )
