"""Rapor export ucu (bonus)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import AnalysisServiceDep, LoadedDatasetDep
from app.api.responses import COMMON_ERRORS
from app.services.report_service import build_report

router = APIRouter(prefix="/datasets/{dataset_id}", tags=["reports"], responses=COMMON_ERRORS)


@router.get(
    "/report.pdf",
    summary="Paylaşılabilir yönetici raporu (PDF)",
    description=(
        "KPI'lar, dönemsel trend, risk sicili ve veri kalitesi notları. "
        "AI analizi önbellekte varsa yönetici özeti ve döneme özgü aksiyonlar da "
        "eklenir; yoksa rapor yalnızca hesaplanmış verilerle üretilir ve AI "
        "çağrısı yapılmaz."
    ),
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def download_report(
    dataset_id: str,
    loaded: LoadedDatasetDep,
    service: AnalysisServiceDep,
    include_ai: bool = Query(
        True, description="Önbellekteki AI analizini rapora dahil et (yeni çağrı yapmaz)"
    ),
) -> Response:
    analysis = None
    if include_ai and await service.is_cached(loaded):
        analysis = await service.analyze(loaded)

    pdf = build_report(
        pack=loaded.pack,
        result=loaded.analytics,
        quality=loaded.quality,
        dataset_name=loaded.record.filename,
        analysis=analysis,
    )
    filename = f"{loaded.pack.key}-{dataset_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
