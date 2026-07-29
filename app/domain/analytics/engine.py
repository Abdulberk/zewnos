"""Zaman serisi analiz motoru.

Pack'ten bagimsizdir: ne hesaplanacagini `DatasetPack` soyler, *nasil*
hesaplanacagini bu modul bilir. Yeni bir rapor tipi eklemek bu dosyaya
dokunmayi gerektirmez.

Uretilen dort tablo:
    series     -- (entity, donem) bazinda zenginlestirilmis uzun tablo
    period     -- donem bazinda portfoy ozeti (grafiklerin kaynagi)
    entity     -- entity bazinda ozet + trend istatistikleri (risklerin kaynagi)
    dimension  -- (boyut, donem) kirilimi (kategori/depo karsilastirmasi)

Kritik detay: tum pencere hesaplari `.over(entity_key)` ile yapilir. Bu
olmadan bir urunun son ayi bir sonraki urunun ilk ayina sizar -- zaman serisi
analizinde en sik ve en sessiz hata budur.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from app.domain.analytics.series import ROW_INDEX as _ROW_INDEX
from app.domain.analytics.series import build_series
from app.domain.models import (
    AnalyticsResult,
    MetricValue,
    PeriodDelta,
    RiskFinding,
    Severity,
)
from app.domain.packs.base import DatasetPack

# Motorun her entity icin urettigi standart trend kolonlari.
# Pack'lerin risk kurallari bu adlara guvenebilir.
TREND_FIRST = "trend_first"
TREND_LAST = "trend_last"
TREND_MEAN = "trend_mean"
TREND_LAST3 = "trend_last3"
TREND_STEP = "trend_step"
TREND_DELTA_PCT = "trend_delta_pct"
PERIOD_COUNT = "periods_count"
FIRST_PERIOD = "first_period"
LAST_PERIOD = "last_period"


def analyze(frame: pl.DataFrame, pack: DatasetPack) -> AnalyticsResult:
    """Temiz tabloyu tam analiz sonucuna cevirir."""
    ctx = pack.context
    series = build_series(frame, pack)

    periods = tuple(series.get_column(ctx.period_key).unique().sort().to_list())
    period_summary = _build_period_summary(series, pack, periods)
    entity_summary = _build_entity_summary(series, pack)
    dimension_summary = _build_dimension_summary(series, pack)

    risks = _evaluate_risks(entity_summary, pack)
    deltas = _build_deltas(series, period_summary, pack, periods, risks)
    headline = _build_headline(period_summary, pack, periods)

    return AnalyticsResult(
        pack_key=pack.key,
        periods=periods,
        entity_count=int(series.get_column(ctx.entity_key).n_unique()),
        headline_metrics=headline,
        period_rows=_rows(period_summary),
        entity_rows=_rows(entity_summary),
        dimension_rows=_rows(dimension_summary),
        series_rows=_rows(series),
        risks=risks,
        deltas=deltas,
    )


# ---------------------------------------------------------------------------
# 2) donem ozeti
# ---------------------------------------------------------------------------
def _build_period_summary(
    series: pl.DataFrame, pack: DatasetPack, periods: tuple[str, ...]
) -> pl.DataFrame:
    ctx = pack.context
    summary = (
        series.group_by(ctx.period_key, maintain_order=True)
        .agg([a.build(ctx).alias(a.name) for a in pack.period_aggregates])
        .sort(ctx.period_key)
    )

    # her toplulastirma icin bir onceki doneme gore degisim
    deltas: list[pl.Expr] = []
    for agg in pack.period_aggregates:
        prev = pl.col(agg.name).shift(1)
        deltas.append((pl.col(agg.name) - prev).alias(f"{agg.name}_delta"))
        deltas.append(
            pl.when(prev.is_null() | (prev == 0))
            .then(None)
            .otherwise((pl.col(agg.name) - prev) / prev.abs() * 100)
            .alias(f"{agg.name}_delta_pct")
        )
    if deltas:
        summary = summary.with_columns(deltas)

    _ = periods  # imza tutarliligi icin; siralama zaten yapildi
    return summary


# ---------------------------------------------------------------------------
# 3) entity ozeti + trend istatistikleri
# ---------------------------------------------------------------------------
def _build_entity_summary(series: pl.DataFrame, pack: DatasetPack) -> pl.DataFrame:
    ctx = pack.context
    trend_col = pack.entity_trend_column or _first_numeric(series, pack)

    aggregations: list[pl.Expr] = [
        pl.col(ctx.entity_label_key).last().alias(ctx.entity_label_key),
        pl.len().alias(PERIOD_COUNT),
        pl.col(ctx.period_key).first().alias(FIRST_PERIOD),
        pl.col(ctx.period_key).last().alias(LAST_PERIOD),
    ]
    aggregations += [pl.col(dim).last().alias(dim) for dim in pack.dimensions]

    if trend_col and trend_col in series.columns:
        aggregations += [
            pl.col(trend_col).first().alias(TREND_FIRST),
            pl.col(trend_col).last().alias(TREND_LAST),
            pl.col(trend_col).mean().alias(TREND_MEAN),
            pl.col(trend_col).tail(3).mean().alias(TREND_LAST3),
        ]

    aggregations += [a.build(ctx).alias(a.name) for a in pack.entity_aggregates]

    summary = series.group_by(ctx.entity_key, maintain_order=True).agg(aggregations)

    if trend_col and trend_col in series.columns:
        n = pl.col(PERIOD_COUNT)
        summary = summary.with_columns(
            [
                # donem basina ortalama degisim -- is tarafina "aylik ortalama
                # +40 adet" diye anlatilabildigi icin egim yerine bunu kullaniyoruz
                pl.when(n > 1)
                .then((pl.col(TREND_LAST) - pl.col(TREND_FIRST)) / (n - 1))
                .otherwise(0.0)
                .alias(TREND_STEP),
                pl.when(pl.col(TREND_FIRST).abs() > 1e-9)
                .then((pl.col(TREND_LAST) - pl.col(TREND_FIRST)) / pl.col(TREND_FIRST).abs() * 100)
                .otherwise(None)
                .alias(TREND_DELTA_PCT),
            ]
        )

    return summary.sort(ctx.entity_key)


def _first_numeric(series: pl.DataFrame, pack: DatasetPack) -> str:
    for name in pack.numeric_columns:
        if name in series.columns:
            return name
    return ""


# ---------------------------------------------------------------------------
# 4) boyut kirilimi
# ---------------------------------------------------------------------------
def _build_dimension_summary(series: pl.DataFrame, pack: DatasetPack) -> pl.DataFrame:
    ctx = pack.context
    if not pack.dimensions or not pack.dimension_aggregates:
        return pl.DataFrame()

    frames: list[pl.DataFrame] = []
    for dim in pack.dimensions:
        if dim not in series.columns:
            continue
        grouped = (
            series.group_by([dim, ctx.period_key], maintain_order=True)
            .agg([a.build(ctx).alias(a.name) for a in pack.dimension_aggregates])
            .rename({dim: "dimension_value"})
            .with_columns(pl.lit(dim).alias("dimension"))
            .sort(["dimension_value", ctx.period_key])
        )
        frames.append(grouped)

    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="vertical_relaxed")


# ---------------------------------------------------------------------------
# 5) risk kurallari
# ---------------------------------------------------------------------------
def _evaluate_risks(entity_summary: pl.DataFrame, pack: DatasetPack) -> tuple[RiskFinding, ...]:
    ctx = pack.context
    findings: list[RiskFinding] = []

    for rule in pack.risk_rules:
        try:
            matched = entity_summary.filter(rule.predicate(ctx).fill_null(False))
        except Exception:
            continue

        for row in matched.iter_rows(named=True):
            evidence = tuple(
                _metric_value(row, name, pack, entity=str(row[ctx.entity_key]))
                for name in rule.evidence_metrics
                if name in row and row[name] is not None
            )
            findings.append(
                RiskFinding(
                    code=rule.code,
                    title=rule.title,
                    severity=rule.severity,
                    entity=str(row[ctx.entity_key]),
                    entity_label=str(row.get(ctx.entity_label_key) or row[ctx.entity_key]),
                    dimension_values={
                        dim: str(row.get(dim) or "") for dim in pack.dimensions if dim in row
                    },
                    narrative=rule.narrative(row),
                    recommendation=rule.recommendation,
                    evidence=evidence,
                    financial_impact_tl=rule.impact(row) if rule.impact else None,
                    first_seen_period=rule.first_seen(row) if rule.first_seen else None,
                )
            )

    findings.sort(key=lambda f: (f.severity.rank, -(f.financial_impact_tl or 0.0), f.entity))
    return tuple(findings)


def _metric_value(
    row: dict[str, Any], name: str, pack: DatasetPack, entity: str | None = None
) -> MetricValue:
    label, unit = _describe_metric(name, pack)
    raw = row.get(name)
    return MetricValue(
        metric=name,
        label=label,
        value=float(raw) if raw is not None else 0.0,
        unit=unit,
        entity=entity,
    )


def _describe_metric(name: str, pack: DatasetPack):
    from app.domain.models import MetricUnit

    for metric in pack.derived_metrics:
        if metric.name == name:
            return metric.label, metric.unit
    for agg in (*pack.period_aggregates, *pack.entity_aggregates, *pack.dimension_aggregates):
        if agg.name == name:
            return agg.label, agg.unit
    column = pack.column(name)
    if column:
        return column.label or name, column.unit
    return name, MetricUnit.SAYI


# ---------------------------------------------------------------------------
# 6) donem deltalari -- "bu ay ne degisti"
# ---------------------------------------------------------------------------
def _build_deltas(
    series: pl.DataFrame,
    period_summary: pl.DataFrame,
    pack: DatasetPack,
    periods: tuple[str, ...],
    risks: tuple[RiskFinding, ...],
) -> tuple[PeriodDelta, ...]:
    ctx = pack.context
    trend_col = pack.entity_trend_column or _first_numeric(series, pack)
    rows = {row[ctx.period_key]: row for row in period_summary.iter_rows(named=True)}

    deltas: list[PeriodDelta] = []
    for index, period in enumerate(periods):
        previous = periods[index - 1] if index else None
        summary_row = rows.get(period, {})

        metrics = tuple(
            _metric_value({**summary_row, agg.name: summary_row.get(agg.name)}, agg.name, pack)
            for agg in pack.period_aggregates
            if summary_row.get(agg.name) is not None
        )

        movers_up: tuple[MetricValue, ...] = ()
        movers_down: tuple[MetricValue, ...] = ()
        if previous and trend_col and trend_col in series.columns:
            movers_up, movers_down = _top_movers(series, pack, trend_col, previous, period)

        deltas.append(
            PeriodDelta(
                period=period,
                previous_period=previous,
                metrics=metrics,
                movers_up=movers_up,
                movers_down=movers_down,
                new_risks=tuple(sorted({r.code for r in risks if r.first_seen_period == period})),
            )
        )
    return tuple(deltas)


def _top_movers(
    series: pl.DataFrame,
    pack: DatasetPack,
    trend_col: str,
    previous: str,
    current: str,
    limit: int = 3,
) -> tuple[tuple[MetricValue, ...], tuple[MetricValue, ...]]:
    """Iki donem arasinda en cok artan / azalan entity'ler."""
    ctx = pack.context
    keys = [ctx.entity_key, ctx.entity_label_key, trend_col]
    subset = series.filter(pl.col(ctx.period_key).is_in([previous, current])).select(
        [*keys, ctx.period_key]
    )

    pivoted = subset.pivot(
        values=trend_col, index=[ctx.entity_key, ctx.entity_label_key], on=ctx.period_key
    )
    if previous not in pivoted.columns or current not in pivoted.columns:
        return (), ()

    changed = pivoted.with_columns(
        (pl.col(current) - pl.col(previous)).alias("__change")
    ).drop_nulls("__change")

    label, unit = _describe_metric(trend_col, pack)

    def build(frame: pl.DataFrame) -> tuple[MetricValue, ...]:
        return tuple(
            MetricValue(
                metric=f"{trend_col}_change",
                label=f"{label} degisimi",
                value=float(row["__change"]),
                unit=unit,
                entity=str(row[ctx.entity_key]),
                period=current,
            )
            for row in frame.iter_rows(named=True)
        )

    up = changed.filter(pl.col("__change") > 0).sort("__change", descending=True).head(limit)
    down = changed.filter(pl.col("__change") < 0).sort("__change").head(limit)
    return build(up), build(down)


# ---------------------------------------------------------------------------
# 7) ust KPI kartlari
# ---------------------------------------------------------------------------
def _build_headline(
    period_summary: pl.DataFrame, pack: DatasetPack, periods: tuple[str, ...]
) -> tuple[MetricValue, ...]:
    if not periods or period_summary.height == 0:
        return ()
    last = period_summary.filter(pl.col(pack.period_key) == periods[-1])
    if last.height == 0:
        return ()
    row = last.to_dicts()[0]
    return tuple(
        MetricValue(
            metric=agg.name,
            label=agg.label,
            value=float(row[agg.name]),
            unit=agg.unit,
            period=periods[-1],
        )
        for agg in pack.headline_aggregates
        if row.get(agg.name) is not None
    )


# ---------------------------------------------------------------------------
def _rows(frame: pl.DataFrame) -> tuple[dict[str, Any], ...]:
    if frame.height == 0:
        return ()
    hidden = {_ROW_INDEX}
    keep = [c for c in frame.columns if c not in hidden and not c.startswith("__")]
    return tuple(frame.select(keep).to_dicts())


def severity_order(finding: RiskFinding) -> int:
    return finding.severity.rank if isinstance(finding.severity, Severity) else 9
