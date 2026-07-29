"""Domain deger nesneleri.

Bu modul kasten cerceve-bagimsizdir (FastAPI / SQLAlchemy / Anthropic yok).
`.importlinter` sozlesmesi bunu CI'da dogrular. Amac: analitik cekirdegi
hicbir altyapi ayaga kaldirmadan dogrudan unit test edebilmek.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ---------------------------------------------------------------------------
# Enum'lar
# ---------------------------------------------------------------------------
class Severity(StrEnum):
    """Bir bulgunun is etkisi. Siralama onceliklendirmede kullanilir."""

    KRITIK = "kritik"
    YUKSEK = "yuksek"
    ORTA = "orta"
    DUSUK = "dusuk"
    BILGI = "bilgi"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.KRITIK: 0,
    Severity.YUKSEK: 1,
    Severity.ORTA: 2,
    Severity.DUSUK: 3,
    Severity.BILGI: 4,
}


class IssueAction(StrEnum):
    """Kalite hattinin bir soruna karsi ne yaptigi.

    Kullaniciya "sorunu buldum" demek yetmez; "ne yaptim" da soylenmeli.
    """

    ONARILDI = "onarildi"  # deger duzeltildi (or. encoding)
    TURETILDI = "turetildi"  # eksik deger mutabakattan hesaplandi
    SILINDI = "silindi"  # birebir kopya satir kaldirildi
    KARANTINA = "karantina"  # satir analiz disi birakildi
    ISARETLENDI = "isaretlendi"  # veri korundu, sadece uyari verildi


class MetricUnit(StrEnum):
    TL = "TL"
    ADET = "adet"
    YUZDE = "%"
    AY = "ay"
    ORAN = "oran"
    SAYI = "sayi"


class ColumnType(StrEnum):
    METIN = "metin"
    TAMSAYI = "tamsayi"
    ONDALIK = "ondalik"
    DONEM = "donem"  # YYYY-MM


class TrendDirection(StrEnum):
    ARTIYOR = "artiyor"
    AZALIYOR = "azaliyor"
    SABIT = "sabit"


# ---------------------------------------------------------------------------
# Veri kalitesi
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class QualityIssue:
    """Ingestion sirasinda tespit edilen tek bir veri kalitesi bulgusu."""

    code: str
    title: str
    severity: Severity
    action: IssueAction
    affected_rows: int
    detail: str
    samples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity.value,
            "action": self.action.value,
            "affected_rows": self.affected_rows,
            "detail": self.detail,
            "samples": list(self.samples),
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Bir yuklemenin kalite ozeti."""

    raw_row_count: int
    clean_row_count: int
    quarantined_row_count: int
    encoding_detected: str
    encoding_repaired: bool
    issues: tuple[QualityIssue, ...]

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def has_blocking_issues(self) -> bool:
        return self.clean_row_count == 0

    @property
    def health_score(self) -> int:
        """0-100 arasi veri saglik puani (dashboard rozeti icin).

        Iki boyutlu: sorunun *agirligi* ve *cozulup cozulmedigi*. Otomatik
        onarilan/turetilen/temizlenen bir sorun tam puan kirmaz -- veri
        kullanilabilir hale gelmistir. Sadece isaretlenip birakilan veya
        karantinaya alinan sorunlar tam agirlikla duser.
        """
        if self.raw_row_count == 0:
            return 0

        weights = {
            Severity.KRITIK: 25.0,
            Severity.YUKSEK: 12.0,
            Severity.ORTA: 6.0,
            Severity.DUSUK: 3.0,
            Severity.BILGI: 1.0,
        }
        resolved = {IssueAction.ONARILDI, IssueAction.TURETILDI, IssueAction.SILINDI}

        penalty = 0.0
        for issue in self.issues:
            weight = weights[issue.severity]
            penalty += weight * (0.4 if issue.action in resolved else 1.0)

        return max(0, min(100, round(100 - penalty)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_row_count": self.raw_row_count,
            "clean_row_count": self.clean_row_count,
            "quarantined_row_count": self.quarantined_row_count,
            "encoding_detected": self.encoding_detected,
            "encoding_repaired": self.encoding_repaired,
            "health_score": self.health_score,
            "issues": [i.to_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Analitik bulgular
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MetricValue:
    """Bir bulgunun dayandigi somut, hesaplanmis sayi.

    Bu tip mimarinin en kritik parcasi: AI'in urettigi her aksiyon en az bir
    MetricValue'ya baglanmak zorunda. Boylece modelin "uydurdugu" bir sayi
    cikti semasindan gecemez.
    """

    metric: str
    label: str
    value: float
    unit: MetricUnit
    entity: str | None = None
    period: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "label": self.label,
            "value": round(self.value, 4),
            "unit": self.unit.value,
            "entity": self.entity,
            "period": self.period,
        }


@dataclass(frozen=True, slots=True)
class RiskFinding:
    """Zaman serisi motorunun tespit ettigi is riski."""

    code: str
    title: str
    severity: Severity
    entity: str
    entity_label: str
    dimension_values: dict[str, str]
    narrative: str
    recommendation: str
    evidence: tuple[MetricValue, ...]
    financial_impact_tl: float | None = None
    first_seen_period: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity.value,
            "entity": self.entity,
            "entity_label": self.entity_label,
            "dimensions": self.dimension_values,
            "narrative": self.narrative,
            "recommendation": self.recommendation,
            "evidence": [e.to_dict() for e in self.evidence],
            "financial_impact_tl": (
                round(self.financial_impact_tl, 2) if self.financial_impact_tl is not None else None
            ),
            "first_seen_period": self.first_seen_period,
        }


@dataclass(frozen=True, slots=True)
class PeriodDelta:
    """Bir donemin bir onceki doneme gore degisimi.

    Donemsel farklilasmanin veri tarafi: AI'a "bu ay ne degisti" diye
    anlatmak yerine hesaplanmis farklari veriyoruz.
    """

    period: str
    previous_period: str | None
    metrics: tuple[MetricValue, ...]
    movers_up: tuple[MetricValue, ...] = ()
    movers_down: tuple[MetricValue, ...] = ()
    new_risks: tuple[str, ...] = ()
    resolved_risks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "previous_period": self.previous_period,
            "metrics": [m.to_dict() for m in self.metrics],
            "movers_up": [m.to_dict() for m in self.movers_up],
            "movers_down": [m.to_dict() for m in self.movers_down],
            "new_risks": list(self.new_risks),
            "resolved_risks": list(self.resolved_risks),
        }


@dataclass(frozen=True, slots=True)
class AnalyticsResult:
    """Zaman serisi motorunun tam ciktisi.

    AI katmani bu nesnenin disinda hicbir veri gormez -- yani modelin
    erisebildigi her sayi burada hesaplanmistir.
    """

    pack_key: str
    periods: tuple[str, ...]
    entity_count: int
    headline_metrics: tuple[MetricValue, ...]
    period_rows: tuple[dict[str, Any], ...] = field(default=())
    entity_rows: tuple[dict[str, Any], ...] = field(default=())
    dimension_rows: tuple[dict[str, Any], ...] = field(default=())
    series_rows: tuple[dict[str, Any], ...] = field(default=())
    risks: tuple[RiskFinding, ...] = field(default=())
    deltas: tuple[PeriodDelta, ...] = field(default=())

    def risks_for_period(self, period: str) -> tuple[RiskFinding, ...]:
        return tuple(r for r in self.risks if r.first_seen_period == period)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_key": self.pack_key,
            "periods": list(self.periods),
            "entity_count": self.entity_count,
            "headline_metrics": [m.to_dict() for m in self.headline_metrics],
            "period_rows": list(self.period_rows),
            "entity_rows": list(self.entity_rows),
            "dimension_rows": list(self.dimension_rows),
            "series_rows": list(self.series_rows),
            "risks": [r.to_dict() for r in self.risks],
            "deltas": [d.to_dict() for d in self.deltas],
        }
