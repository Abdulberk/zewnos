"""Domain nesnelerinden API sozlesmelerine donusum.

Ayri bir katman olmasinin sebebi: domain modeli degistiginde API sozlesmesinin
sessizce degismemesi. Kirilma burada, derleme/test zamaninda goruluyor.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.models import QualityReport, RiskFinding
from app.domain.packs.base import DatasetPack
from app.schemas.common import MetricOut, PackOut, QualityReportOut, RiskOut
from app.schemas.dataset import DatasetSummary
from app.storage.models import Dataset


def dataset_summary(record: Dataset, pack: DatasetPack) -> DatasetSummary:
    return DatasetSummary(
        id=record.id,
        filename=record.filename,
        pack_key=record.pack_key,
        pack_title=pack.title,
        raw_row_count=record.raw_row_count,
        clean_row_count=record.clean_row_count,
        quarantined_row_count=record.quarantined_row_count,
        health_score=record.health_score,
        encoding_detected=record.encoding_detected,
        created_at=record.created_at,
    )


def quality_out(report: QualityReport) -> QualityReportOut:
    return QualityReportOut.model_validate(report.to_dict())


def risk_out(risk: RiskFinding) -> RiskOut:
    return RiskOut.model_validate(risk.to_dict())


def metric_out(metric: Any) -> MetricOut:
    return MetricOut.model_validate(metric.to_dict())


def pack_out(pack: DatasetPack) -> PackOut:
    return PackOut(
        key=pack.key,
        title=pack.title,
        description=pack.description,
        entity_key=pack.entity_key,
        period_key=pack.period_key,
        dimensions=list(pack.dimensions),
        required_columns=list(pack.required_columns),
        risk_rule_count=len(pack.risk_rules),
        metric_count=len(pack.derived_metrics),
        sample_file=pack.sample_file,
    )


def severity_counts(risks: Sequence[RiskFinding]) -> dict[str, int]:
    """Agirlik dagilimi.

    Risk dizisi alir, AnalyticsResult degil: filtrelenmis bir liste geldiginde
    dagilim da o listeyi anlatsin. Aksi halde ?severity=kritik sorgusunda
    total=3 ama dagilim 18 gosterir -- ekranda birbirini tutmayan iki sayi.
    """
    counts: dict[str, int] = {}
    for risk in risks:
        counts[risk.severity.value] = counts.get(risk.severity.value, 0) + 1
    return counts


def code_counts(risks: Sequence[RiskFinding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for risk in risks:
        counts[risk.code] = counts.get(risk.code, 0) + 1
    return counts


def entity_columns(pack: DatasetPack) -> list[dict[str, str]]:
    """Frontend tablo basliklari: teknik ad + insan etiketi + birim."""
    columns: list[dict[str, str]] = [
        {"name": pack.entity_key, "label": "Kod", "unit": ""},
        {"name": pack.entity_label_key, "label": "Ad", "unit": ""},
    ]
    # Boyut etiketi pack'teki ColumnDef'ten gelir. snake_case'i .title() ile
    # insanlastirmak ikinci bir etiket kaynagi yaratirdi ("urun_kategorisi" ->
    # "Urun Kategorisi"); tek dogruluk kaynagi pack olmali.
    labels = {column.canonical: column.label for column in pack.columns}
    columns += [
        {"name": dim, "label": labels.get(dim) or dim.replace("_", " ").title(), "unit": ""}
        for dim in pack.dimensions
    ]
    columns += [
        {"name": agg.name, "label": agg.label, "unit": agg.unit.value}
        for agg in pack.entity_aggregates
        if not agg.internal
    ]
    return columns
