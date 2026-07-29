"""Veri seti uclarinin sozlesmeleri."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import MetricOut, QualityReportOut, RiskOut


class DatasetSummary(BaseModel):
    id: str
    filename: str
    pack_key: str
    pack_title: str
    raw_row_count: int
    clean_row_count: int
    quarantined_row_count: int
    health_score: int
    encoding_detected: str
    created_at: datetime


class UploadResponse(BaseModel):
    dataset: DatasetSummary
    quality: QualityReportOut
    periods: list[str]
    entity_count: int
    risk_count: int


class OverviewResponse(BaseModel):
    dataset: DatasetSummary
    periods: list[str]
    entity_count: int
    headline_metrics: list[MetricOut]
    period_rows: list[dict[str, Any]] = Field(
        description="Donem bazinda portfoy ozeti -- trend grafiklerinin kaynagi."
    )
    risk_counts_by_severity: dict[str, int]
    top_risks: list[RiskOut]


class PeriodsResponse(BaseModel):
    periods: list[str]
    rows: list[dict[str, Any]]
    deltas: list[dict[str, Any]] = Field(
        description="Her donemin bir oncekine gore degisimi ve o donemde acilan riskler."
    )
    dimension_rows: list[dict[str, Any]]


class EntitiesResponse(BaseModel):
    entity_key: str
    entity_label_key: str
    dimensions: list[str]
    columns: list[dict[str, str]] = Field(
        description="Kolon adi/etiket/birim -- tablo basliklarini frontend'e tasir."
    )
    rows: list[dict[str, Any]]
    series_rows: list[dict[str, Any]] = Field(
        description="(kayit, donem) bazinda uzun tablo -- kayit detay grafikleri icin."
    )


class RisksResponse(BaseModel):
    total: int
    total_financial_impact_tl: float
    by_severity: dict[str, int]
    by_code: dict[str, int]
    risks: list[RiskOut]
