"""Rapor export ucu (bonus)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import AnalysisServiceDep, LoadedDatasetDep
from app.services.report_service import build_report

router = APIRouter(prefix="/datasets/{dataset_id}", tags=["reports"])


@router.get(
    "/report.pdf",
    summary="Paylasilabilir yonetici raporu (PDF)",
    description=(
        "KPI'lar, donemsel trend, risk sicili ve veri kalitesi notlari. "
        "AI analizi onbellekte varsa yonetici ozeti ve doneme ozgu aksiyonlar da "
        "eklenir; yoksa rapor yalnizca hesaplanmis verilerle uretilir ve AI "
        "cagrisi yapilmaz."
    ),
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def download_report(
    dataset_id: str,
    loaded: LoadedDatasetDep,
    service: AnalysisServiceDep,
    include_ai: bool = Query(
        True, description="Onbellekteki AI analizini rapora dahil et (yeni cagri yapmaz)"
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
