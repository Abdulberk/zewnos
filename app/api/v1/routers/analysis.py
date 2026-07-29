"""AI analiz ve soru-cevap uclari."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import AnalysisServiceDep, LoadedDatasetDep, SettingsDep
from app.schemas.analysis import (
    AnalysisResponse,
    AnalysisStatusResponse,
    AskRequest,
    AskResponse,
)

router = APIRouter(prefix="/datasets/{dataset_id}", tags=["analysis"])


@router.get(
    "/analysis/status",
    response_model=AnalysisStatusResponse,
    summary="Analiz hazir mi, kac cagri gerekecek",
    description=(
        "Frontend'in 'analiz uret' butonunu maliyet uyarisiyla gostermesi icin. "
        "Onbellekte varsa cagri yapilmayacagini bildirir."
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
    summary="Donemsel analiz + yonetici ozeti uret",
    description=(
        "Her donem icin paralel bir AI cagrisi, ardindan tek bir sentez cagrisi. "
        "Sonuc onbellege yazilir; ayni veri seti icin tekrar cagrildiginda AI'a "
        "gidilmez. `refresh=true` ile yeniden uretilebilir."
    ),
)
async def create_analysis(
    dataset_id: str,
    loaded: LoadedDatasetDep,
    service: AnalysisServiceDep,
    settings: SettingsDep,
    refresh: bool = Query(False, description="Onbellegi yok say ve yeniden uret"),
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
    summary="Veri uzerinde serbest soru-cevap",
    description=(
        "Model SQL yazmaz: hesaplanmis tablolari yorumlar. Boylece 'AI sayi "
        "hesaplamaz' kurali soru-cevapta da korunur ve her yanit kanit tasir."
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
