"""Veri seti uclari: yukleme, listeleme, kalite, dashboard verileri."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import DatasetServiceDep, LoadedDatasetDep
from app.api.mappers import (
    code_counts,
    dataset_summary,
    entity_columns,
    metric_out,
    quality_out,
    risk_out,
    severity_counts,
)
from app.api.responses import UPLOAD_ERRORS
from app.schemas.common import QualityReportOut
from app.schemas.dataset import (
    DatasetSummary,
    EntitiesResponse,
    OverviewResponse,
    PeriodsResponse,
    RisksResponse,
    UploadResponse,
)
from app.services.registry import get_pack

router = APIRouter(prefix="/datasets", tags=["datasets"], responses=UPLOAD_ERRORS)


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="CSV yükle ve işle",
)
async def upload_dataset(
    service: DatasetServiceDep,
    file: UploadFile = File(..., description="İşlenecek CSV dosyası"),
    pack: str | None = Form(
        None,
        description="Rapor tipi (ör. 'sonart-erp'). Boş bırakılırsa başlıklardan tespit edilir.",
    ),
) -> UploadResponse:
    raw = await file.read()
    loaded = await service.create(raw, file.filename or "upload.csv", pack)
    return UploadResponse(
        dataset=dataset_summary(loaded.record, loaded.pack),
        quality=quality_out(loaded.quality),
        periods=list(loaded.analytics.periods),
        entity_count=loaded.analytics.entity_count,
        risk_count=len(loaded.analytics.risks),
    )


@router.get("", response_model=list[DatasetSummary], summary="Yüklenmiş veri setleri")
async def list_datasets(service: DatasetServiceDep) -> list[DatasetSummary]:
    records = await service.list()
    return [dataset_summary(record, get_pack(record.pack_key)) for record in records]


@router.get("/{dataset_id}", response_model=DatasetSummary, summary="Veri seti özeti")
async def get_dataset(loaded: LoadedDatasetDep) -> DatasetSummary:
    return dataset_summary(loaded.record, loaded.pack)


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Veri setini sil",
)
async def delete_dataset(dataset_id: str, service: DatasetServiceDep) -> Response:
    await service.delete(dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{dataset_id}/quality",
    response_model=QualityReportOut,
    summary="Veri kalitesi raporu",
    description=(
        "Tespit edilen her sorun; ağırlığı, kaç satırı etkilediği ve **ne yapıldığı** "
        "(onarildi / turetildi / silindi / karantina / isaretlendi) ile birlikte."
    ),
)
async def get_quality(loaded: LoadedDatasetDep) -> QualityReportOut:
    return quality_out(loaded.quality)


@router.get("/{dataset_id}/overview", response_model=OverviewResponse, summary="Dashboard özeti")
async def get_overview(
    loaded: LoadedDatasetDep,
    top: int = Query(8, ge=1, le=50, description="Dönülecek risk sayısı"),
) -> OverviewResponse:
    result = loaded.analytics
    return OverviewResponse(
        dataset=dataset_summary(loaded.record, loaded.pack),
        periods=list(result.periods),
        entity_count=result.entity_count,
        headline_metrics=[metric_out(m) for m in result.headline_metrics],
        period_rows=list(result.period_rows),
        risk_counts_by_severity=severity_counts(result.risks),
        top_risks=[risk_out(r) for r in result.risks[:top]],
    )


@router.get(
    "/{dataset_id}/periods",
    response_model=PeriodsResponse,
    summary="Dönemsel trend ve değişim verisi",
)
async def get_periods(loaded: LoadedDatasetDep) -> PeriodsResponse:
    result = loaded.analytics
    return PeriodsResponse(
        periods=list(result.periods),
        rows=list(result.period_rows),
        deltas=[d.to_dict() for d in result.deltas],
        dimension_rows=list(result.dimension_rows),
    )


@router.get(
    "/{dataset_id}/entities",
    response_model=EntitiesResponse,
    summary="Kayıt bazında özet ve zaman serisi",
)
async def get_entities(
    loaded: LoadedDatasetDep,
    include_series: bool = Query(True, description="(kayıt, dönem) uzun tablosunu da döndür"),
) -> EntitiesResponse:
    result = loaded.analytics
    pack = loaded.pack
    return EntitiesResponse(
        entity_key=pack.entity_key,
        entity_label_key=pack.entity_label_key,
        dimensions=list(pack.dimensions),
        columns=entity_columns(pack),
        rows=list(result.entity_rows),
        series_rows=list(result.series_rows) if include_series else [],
    )


@router.get("/{dataset_id}/risks", response_model=RisksResponse, summary="Risk sicili")
async def get_risks(
    loaded: LoadedDatasetDep,
    severity: str | None = Query(None, description="Ağırlığa göre filtre, ör. 'kritik'"),
    period: str | None = Query(None, description="Yalnızca bu dönemde açılan riskler"),
) -> RisksResponse:
    result = loaded.analytics
    risks = list(result.risks)
    if severity:
        risks = [r for r in risks if r.severity.value == severity]
    if period:
        risks = [r for r in risks if r.first_seen_period == period]

    return RisksResponse(
        total=len(risks),
        total_financial_impact_tl=round(sum(r.financial_impact_tl or 0.0 for r in risks), 2),
        by_severity=severity_counts(risks),
        by_code=code_counts(risks),
        risks=[risk_out(r) for r in risks],
    )
