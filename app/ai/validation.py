"""AI ciktisinin veriye dayandirilmasi (grounding).

Sema, modeli her aksiyona kanit eklemeye zorlar. Bu modul bir adim ileri
gider ve **kanitlarin gercek oldugunu** dogrular: modelin yazdigi her
(metrik, kayit, donem, deger) dortlusu motorun urettigi tablolarda aranir.

Bulunamayan ya da tutmayan kanitlar isaretlenir ve bir "grounding orani"
raporlanir. Boylece halusinasyon sessizce gecmez; olcunur ve gosterilir.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.ai.ai_schemas import Evidence
from app.domain.models import AnalyticsResult
from app.domain.packs.base import DatasetPack

# Goreli tolerans: modelin yuvarlama yapmasi (33.480 -> 33.5 bin) hata sayilmasin.
RELATIVE_TOLERANCE = 0.02
ABSOLUTE_TOLERANCE = 0.51


@dataclass(slots=True)
class EvidenceIssue:
    metric: str
    entity: str | None
    period: str | None
    claimed: float
    expected: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "entity": self.entity,
            "period": self.period,
            "claimed": self.claimed,
            "expected": self.expected,
            "reason": self.reason,
        }


@dataclass(slots=True)
class GroundingReport:
    """AI ciktisinin ne kadarinin hesaplanmis veriye dayandigi."""

    total: int = 0
    verified: int = 0
    issues: list[EvidenceIssue] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return 1.0 if self.total == 0 else self.verified / self.total

    @property
    def is_acceptable(self) -> bool:
        """Kanitlarin en az %80'i dogrulanabiliyorsa cikti kabul edilir."""
        return self.total == 0 or self.ratio >= 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evidence": self.total,
            "verified_evidence": self.verified,
            "grounding_ratio": round(self.ratio, 4),
            "issues": [i.to_dict() for i in self.issues[:20]],
        }


_TR_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _norm(value: str | None) -> str | None:
    """Kayit/boyut adlarini karsilastirma icin normalize eder.

    Model bazen Turkce karakterleri ASCII'ye dusurerek yaziyor ("Dosemelik"
    yerine "Döşemelik"). Bu bir halusinasyon degil, sadece yazim farki --
    normalize etmezsek gecerli bir kaniti yanlislikla "bulunamadi" diye
    raporlar ve grounding oranini haksiz yere dusururuz.
    """
    if value is None:
        return None
    return value.translate(_TR_FOLD).casefold().strip()


class FactIndex:
    """Motorun urettigi tum sayilarin aranabilir dizini."""

    def __init__(self, result: AnalyticsResult, pack: DatasetPack) -> None:
        self._values: dict[tuple[str, str | None, str | None], float] = {}
        entity_key = pack.entity_key
        period_key = pack.period_key

        def put(metric: str, entity: str | None, period: str | None, value: Any) -> None:
            if isinstance(value, int | float) and not isinstance(value, bool):
                self._values[(metric, _norm(entity), period)] = float(value)

        for row in result.period_rows:
            period = str(row.get(period_key)) if row.get(period_key) else None
            for key, value in row.items():
                put(key, None, period, value)

        for row in result.entity_rows:
            entity = str(row.get(entity_key)) if row.get(entity_key) else None
            for key, value in row.items():
                put(key, entity, None, value)

        # Boyut kirilimi (kategori/depo). Model dogru sekilde "Cantalik kategorisinin
        # marji" gibi degerlere atif yapiyor; bunlari indekslemezsek portfoy geneline
        # duser ve gecerli bir kanit yanlislikla "sapma" olarak raporlanir.
        for row in result.dimension_rows:
            value_name = row.get("dimension_value")
            period = str(row.get(period_key)) if row.get(period_key) else None
            label = str(value_name) if value_name else None
            for key, value in row.items():
                put(key, label, period, value)
                put(key, label, None, value)

        for row in result.series_rows:
            entity = str(row.get(entity_key)) if row.get(entity_key) else None
            period = str(row.get(period_key)) if row.get(period_key) else None
            for key, value in row.items():
                put(key, entity, period, value)

        for metric in result.headline_metrics:
            put(metric.metric, None, metric.period, metric.value)

        # Donem deltalari: portfoy metrikleri ve "en cok artan/azalan" degerleri.
        for delta in result.deltas:
            for metric in (*delta.metrics, *delta.movers_up, *delta.movers_down):
                put(metric.metric, metric.entity, metric.period or delta.period, metric.value)
                put(metric.metric, metric.entity, None, metric.value)

        for risk in result.risks:
            if risk.financial_impact_tl is not None:
                put("financial_impact_tl", risk.entity, None, risk.financial_impact_tl)
            for item in risk.evidence:
                put(item.metric, item.entity, item.period, item.value)

    def lookup(self, metric: str, entity: str | None, period: str | None) -> float | None:
        """Once tam eslesme, sonra giderek gevseyen anahtarlar denenir.

        Gevsetme sirasi onemli: entity'yi dusurmeden once donemi dusuruyoruz,
        cunku bir kaydin kendi degeri portfoy genelinden daha spesifiktir.
        """
        key = _norm(entity)
        for candidate in (
            (metric, key, period),
            (metric, key, None),
            (metric, None, period),
            (metric, None, None),
        ):
            if candidate in self._values:
                return self._values[candidate]
        return None


def verify(evidence_items: Iterable[Evidence], index: FactIndex) -> GroundingReport:
    report = GroundingReport()
    for item in evidence_items:
        report.total += 1
        expected = index.lookup(item.metric, item.entity, item.period)

        if expected is None:
            report.issues.append(
                EvidenceIssue(
                    metric=item.metric,
                    entity=item.entity,
                    period=item.period,
                    claimed=item.value,
                    expected=None,
                    reason="Metrik hesaplanmis tablolarda bulunamadi.",
                )
            )
            continue

        tolerance = max(ABSOLUTE_TOLERANCE, abs(expected) * RELATIVE_TOLERANCE)
        if abs(item.value - expected) <= tolerance:
            report.verified += 1
        else:
            report.issues.append(
                EvidenceIssue(
                    metric=item.metric,
                    entity=item.entity,
                    period=item.period,
                    claimed=item.value,
                    expected=expected,
                    reason="Deger hesaplanan sayidan sapiyor.",
                )
            )
    return report


def collect_evidence(payload: Any) -> list[Evidence]:
    """Ic ice gecmis Pydantic modellerinden tum Evidence nesnelerini toplar."""
    found: list[Evidence] = []

    def walk(node: Any) -> None:
        if isinstance(node, Evidence):
            found.append(node)
            return
        if isinstance(node, list | tuple):
            for child in node:
                walk(child)
            return
        if hasattr(node, "__pydantic_fields__"):
            for name in type(node).__pydantic_fields__:
                walk(getattr(node, name, None))

    walk(payload)
    return found
