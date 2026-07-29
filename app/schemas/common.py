"""Paylasilan API sozlesmeleri."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Tum hatalarin ortak govdesi.

    Istemci `code` alanina gore dallanir; mesaj metni degisse bile kirilmaz.
    """

    code: str = Field(examples=["schema_mismatch"])
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MetricOut(BaseModel):
    metric: str
    label: str
    value: float
    unit: str
    entity: str | None = None
    period: str | None = None


class QualityIssueOut(BaseModel):
    code: str
    title: str
    severity: str
    action: str
    affected_rows: int
    detail: str
    samples: list[str] = Field(default_factory=list)


class QualityReportOut(BaseModel):
    raw_row_count: int
    clean_row_count: int
    quarantined_row_count: int
    encoding_detected: str
    encoding_repaired: bool
    health_score: int
    issues: list[QualityIssueOut]


class RiskOut(BaseModel):
    code: str
    title: str
    severity: str
    entity: str
    entity_label: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    narrative: str
    recommendation: str
    evidence: list[MetricOut] = Field(default_factory=list)
    financial_impact_tl: float | None = None
    first_seen_period: str | None = None


class PackOut(BaseModel):
    key: str
    title: str
    description: str
    entity_key: str
    period_key: str
    dimensions: list[str]
    required_columns: list[str]
    risk_rule_count: int
    metric_count: int
    sample_file: str


class TelemetryOut(BaseModel):
    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cache_hit_calls: int = 0
    total_cost_usd: float = 0.0
    duration_ms: int = 0


class GroundingOut(BaseModel):
    """AI ciktisinin ne kadarinin hesaplanmis veriye dayandigi."""

    total_evidence: int
    verified_evidence: int
    grounding_ratio: float
    issues: list[dict[str, Any]] = Field(default_factory=list)
