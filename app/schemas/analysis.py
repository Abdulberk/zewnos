"""AI analiz uclarinin sozlesmeleri."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.ai.ai_schemas import ExecutiveSummary, PeriodAnalysis, QAAnswer
from app.schemas.common import GroundingOut, TelemetryOut


class AnalysisResponse(BaseModel):
    dataset_id: str
    pack_key: str
    model: str
    cached: bool = Field(description="True ise sonuc onbellekten geldi; yeni AI cagrisi yapilmadi.")
    cached_at: str | None = None
    periods: list[PeriodAnalysis]
    summary: ExecutiveSummary | None
    grounding: GroundingOut
    telemetry: TelemetryOut
    failed_periods: list[dict[str, str]] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(
        min_length=3, max_length=500, examples=["Marji en hizli daralan urun hangisi?"]
    )


class AskResponse(BaseModel):
    dataset_id: str
    question: str
    answer: QAAnswer
    grounding: GroundingOut
    telemetry: TelemetryOut
    cached: bool = False


class AnalysisStatusResponse(BaseModel):
    dataset_id: str
    ai_configured: bool
    cached: bool
    model: str
    effort: str
    estimated_calls: int
    detail: dict[str, Any] = Field(default_factory=dict)
