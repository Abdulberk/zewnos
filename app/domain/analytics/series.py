"""Zenginlestirilmis uzun tablonun insasi.

Hem kalite hatti (butunluk kurallari icin) hem analiz motoru ayni tabloyu
kullanir; tek yerde tanimli olmasi ikisinin ayrisma ihtimalini ortadan
kaldirir.
"""

from __future__ import annotations

import polars as pl

from app.domain.packs.base import DatasetPack

ROW_INDEX = "__row_idx"


def build_series(frame: pl.DataFrame, pack: DatasetPack) -> pl.DataFrame:
    """Ham temiz tabloya turetilmis metrikleri ekler.

    Iki kritik detay:

    1) Metrikler **tek tek** eklenir, hepsi birden degil. Polars ayni
       `with_columns` cagrisindaki ifadeleri birbirinden bagimsiz degerlendirir;
       bir metrik ayni cagrida uretilen digerine erisemez. Sirali ekleme
       sayesinde `kapama_ay` kendisinden once tanimlanan `cikis_ort3`'u
       kullanabiliyor. Pack'teki tanim sirasi = bagimlilik sirasi.

    2) Once satir ici, sonra pencere metrikleri. Tum pencere hesaplari
       `.over(entity_key)` tasir; bu olmadan bir urunun son donemi bir sonraki
       urunun ilk donemine sizar.
    """
    ctx = pack.context
    series = frame.sort([ctx.entity_key, ctx.period_key])

    for metric in pack.derived_metrics:
        if metric.stage != "row":
            continue
        series = series.with_columns(metric.build(ctx).alias(metric.name))

    series = series.with_columns(pl.int_range(pl.len()).over(ctx.entity_key).alias(ROW_INDEX))

    for metric in pack.derived_metrics:
        if metric.stage != "window":
            continue
        series = series.with_columns(metric.build(ctx).alias(metric.name))

    return series
