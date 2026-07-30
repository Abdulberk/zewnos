"""Zewnos -- Meta/Instagram reklam performans raporu pack'i.

Bu dosya mimarinin jenerikligini KANITLAR. Ingestion, kalite hatti, zaman
serisi motoru, risk degerlendirmesi, AI orkestrasyonu ve tum API uclari
degismeden bu raporu da isler. Yeni bir rapor eklemek = yeni bir pack yazmak.

Kaynak kolonlar:
    kampanya_id, kampanya_adi, platform, urun_kategorisi, donem,
    harcama_tl, gosterim, tiklama, frekans, donusum, gelir_tl
"""

from __future__ import annotations

import polars as pl

from app.domain.models import ColumnType, IssueAction, MetricUnit, Severity
from app.domain.packs.base import (
    Aggregate,
    ColumnDef,
    DatasetPack,
    Department,
    DerivedMetric,
    ImputationRule,
    IntegrityRule,
    PromptProfile,
    RiskRule,
    RowMapping,
)

# --- esikler ---------------------------------------------------------------
ROAS_ZARAR = 1.0  # bunun altinda kampanya para kaybediyor
ROAS_YILDIZ = 3.0  # bunun ustunde olceklenmeye deger
FREKANS_DOYUM = 2.5  # bunun ustunde kitle yorulmasi baslar
ROAS_DUSUS_YUZDE = -25.0  # donem basindan bu yana kabul edilebilir dusus siniri
HARCAMA_ARTIS_YUZDE = 50.0  # "olcekleniyor" sayilacak harcama artisi


def _num(row: RowMapping, key: str, default: float = 0.0) -> float:
    value = row.get(key)
    return float(value) if value is not None else default


def _tl(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") + " TL"


COLUMNS = (
    ColumnDef("kampanya_id", ("campaign_id",), ColumnType.METIN, True, "Kampanya Kodu"),
    ColumnDef("kampanya_adi", ("campaign_name",), ColumnType.METIN, True, "Kampanya"),
    ColumnDef("platform", (), ColumnType.METIN, True, "Platform"),
    ColumnDef("urun_kategorisi", ("kategori",), ColumnType.METIN, True, "Ürün Kategorisi"),
    ColumnDef("donem", ("period", "ay"), ColumnType.DONEM, True, "Dönem"),
    ColumnDef(
        "harcama_tl", ("harcama", "spend"), ColumnType.ONDALIK, True, "Harcama", MetricUnit.TL
    ),
    ColumnDef("gosterim", ("impressions",), ColumnType.ONDALIK, True, "Gösterim", MetricUnit.ADET),
    ColumnDef("tiklama", ("clicks",), ColumnType.ONDALIK, True, "Tıklama", MetricUnit.ADET),
    ColumnDef("frekans", ("frequency",), ColumnType.ONDALIK, True, "Frekans", MetricUnit.ORAN),
    ColumnDef(
        "donusum",
        ("conversions", "donusumler"),
        ColumnType.ONDALIK,
        True,
        "Dönüşüm",
        MetricUnit.ADET,
    ),
    ColumnDef("gelir_tl", ("gelir", "revenue"), ColumnType.ONDALIK, True, "Gelir", MetricUnit.TL),
)


def _safe_ratio(numerator: pl.Expr, denominator: pl.Expr, scale: float = 1.0) -> pl.Expr:
    return pl.when(denominator > 0).then(numerator / denominator * scale).otherwise(None)


DERIVED_METRICS = (
    DerivedMetric(
        "roas",
        "ROAS",
        MetricUnit.ORAN,
        lambda _: _safe_ratio(pl.col("gelir_tl"), pl.col("harcama_tl")),
        "row",
        "Reklam harcamasının geri dönüşü: gelir / harcama.",
    ),
    DerivedMetric(
        "net_kar_tl",
        "Net Katkı",
        MetricUnit.TL,
        lambda _: pl.col("gelir_tl") - pl.col("harcama_tl"),
        "row",
    ),
    DerivedMetric(
        "ctr",
        "Tıklama Oranı",
        MetricUnit.YUZDE,
        lambda _: _safe_ratio(pl.col("tiklama"), pl.col("gosterim"), 100),
        "row",
    ),
    DerivedMetric(
        "cpc",
        "Tıklama Başı Maliyet",
        MetricUnit.TL,
        lambda _: _safe_ratio(pl.col("harcama_tl"), pl.col("tiklama")),
        "row",
    ),
    DerivedMetric(
        "cpm",
        "Bin Gösterim Maliyeti",
        MetricUnit.TL,
        lambda _: _safe_ratio(pl.col("harcama_tl"), pl.col("gosterim"), 1000),
        "row",
    ),
    DerivedMetric(
        "cpa",
        "Dönüşüm Başı Maliyet",
        MetricUnit.TL,
        lambda _: _safe_ratio(pl.col("harcama_tl"), pl.col("donusum")),
        "row",
    ),
    DerivedMetric(
        "cvr",
        "Dönüşüm Oranı",
        MetricUnit.YUZDE,
        lambda _: _safe_ratio(pl.col("donusum"), pl.col("tiklama"), 100),
        "row",
    ),
    # --- pencere ---
    DerivedMetric(
        "roas_mom_yuzde",
        "ROAS Değişimi (Aylık)",
        MetricUnit.YUZDE,
        lambda ctx: pl.col("roas").pct_change().over(ctx.entity_key) * 100,
        "window",
    ),
    DerivedMetric(
        "harcama_mom_yuzde",
        "Harcama Değişimi (Aylık)",
        MetricUnit.YUZDE,
        lambda ctx: pl.col("harcama_tl").pct_change().over(ctx.entity_key) * 100,
        "window",
    ),
    DerivedMetric(
        "tiklama_mom_yuzde",
        "Tıklama Değişimi (Aylık)",
        MetricUnit.YUZDE,
        lambda ctx: pl.col("tiklama").pct_change().over(ctx.entity_key) * 100,
        "window",
    ),
    DerivedMetric(
        "frekans_delta",
        "Frekans Değişimi",
        MetricUnit.ORAN,
        lambda ctx: pl.col("frekans") - pl.col("frekans").shift(1).over(ctx.entity_key),
        "window",
    ),
    DerivedMetric(
        "roas_ort3",
        "ROAS (3 Dönem Ort.)",
        MetricUnit.ORAN,
        lambda ctx: pl.col("roas").rolling_mean(window_size=3, min_periods=1).over(ctx.entity_key),
        "window",
    ),
)


IMPUTATION_RULES = (
    ImputationRule(
        code="IMPUTED_SPEND",
        title="Eksik harcama kampanyanın kendi ortancasından tamamlandı",
        target_column="harcama_tl",
        forward=lambda ctx: pl.col("harcama_tl").median().over(ctx.entity_key),
        detail="Eksik harcama, aynı kampanyanın diğer dönemlerindeki ortanca değerle dolduruldu.",
    ),
    ImputationRule(
        code="IMPUTED_METRICS",
        title="Eksik gösterim/tıklama/dönüşüm/gelir değerleri tamamlandı",
        target_column="gosterim",
        forward=lambda ctx: pl.col("gosterim").median().over(ctx.entity_key),
        detail="Eksik gösterim ortanca ile dolduruldu.",
    ),
    ImputationRule(
        code="IMPUTED_METRICS",
        title="Eksik tıklama tamamlandı",
        target_column="tiklama",
        forward=lambda ctx: pl.col("tiklama").median().over(ctx.entity_key),
        detail="Eksik tıklama ortanca ile dolduruldu.",
    ),
    ImputationRule(
        code="IMPUTED_METRICS",
        title="Eksik frekans tamamlandı",
        target_column="frekans",
        forward=lambda ctx: pl.col("frekans").median().over(ctx.entity_key),
        detail="Eksik frekans ortanca ile dolduruldu.",
    ),
    ImputationRule(
        code="IMPUTED_METRICS",
        title="Eksik dönüşüm tamamlandı",
        target_column="donusum",
        forward=lambda ctx: pl.col("donusum").median().over(ctx.entity_key),
        detail="Eksik dönüşüm ortanca ile dolduruldu.",
    ),
    ImputationRule(
        code="IMPUTED_METRICS",
        title="Eksik gelir tamamlandı",
        target_column="gelir_tl",
        forward=lambda ctx: pl.col("gelir_tl").median().over(ctx.entity_key),
        detail="Eksik gelir ortanca ile dolduruldu.",
    ),
)


INTEGRITY_RULES = (
    IntegrityRule(
        code="CLICKS_EXCEED_IMPRESSIONS",
        title="Tıklama gösterimden fazla",
        severity=Severity.KRITIK,
        action=IssueAction.ISARETLENDI,
        violation=lambda _: pl.col("tiklama") > pl.col("gosterim"),
        detail_template="{count} kayıtta tıklama gösterimi aşıyor; ölçüm hatası olmalı.",
        sample_columns=("kampanya_id", "donem", "tiklama", "gosterim"),
    ),
    IntegrityRule(
        code="CONVERSIONS_EXCEED_CLICKS",
        title="Dönüşüm tıklamadan fazla",
        severity=Severity.YUKSEK,
        action=IssueAction.ISARETLENDI,
        violation=lambda _: pl.col("donusum") > pl.col("tiklama"),
        detail_template="{count} kayıtta dönüşüm tıklamadan fazla; atıf penceresi kaymış olabilir.",
        sample_columns=("kampanya_id", "donem", "donusum", "tiklama"),
    ),
    IntegrityRule(
        code="NEGATIVE_VALUE",
        title="Negatif metrik",
        severity=Severity.KRITIK,
        action=IssueAction.ISARETLENDI,
        violation=lambda _: (pl.col("harcama_tl") < 0) | (pl.col("gelir_tl") < 0),
        detail_template="{count} kayıtta negatif harcama veya gelir var.",
        sample_columns=("kampanya_id", "donem", "harcama_tl", "gelir_tl"),
    ),
    IntegrityRule(
        code="SPEND_WITHOUT_DELIVERY",
        title="Harcama var ama gösterim yok",
        severity=Severity.YUKSEK,
        action=IssueAction.ISARETLENDI,
        violation=lambda _: (pl.col("harcama_tl") > 0) & (pl.col("gosterim") <= 0),
        detail_template="{count} kayıtta bütçe harcanmış ama hiçbir gösterim kaydedilmemiş.",
        sample_columns=("kampanya_id", "donem", "harcama_tl", "gosterim"),
    ),
)


PERIOD_AGGREGATES = (
    Aggregate(
        "toplam_harcama_tl",
        "Toplam Harcama",
        MetricUnit.TL,
        lambda _: pl.col("harcama_tl").sum(),
        True,
    ),
    Aggregate(
        "toplam_gelir_tl", "Toplam Gelir", MetricUnit.TL, lambda _: pl.col("gelir_tl").sum(), True
    ),
    Aggregate(
        "portfoy_roas",
        "Portföy ROAS",
        MetricUnit.ORAN,
        lambda _: _safe_ratio(pl.col("gelir_tl").sum(), pl.col("harcama_tl").sum()),
        True,
    ),
    Aggregate(
        "net_katki_tl",
        "Net Katkı",
        MetricUnit.TL,
        lambda _: pl.col("gelir_tl").sum() - pl.col("harcama_tl").sum(),
        True,
    ),
    Aggregate(
        "zarardaki_kampanya",
        "Zarardaki Kampanya",
        MetricUnit.SAYI,
        lambda _: (pl.col("roas") < ROAS_ZARAR).sum(),
        True,
    ),
    Aggregate(
        "toplam_donusum", "Toplam Dönüşüm", MetricUnit.ADET, lambda _: pl.col("donusum").sum()
    ),
    Aggregate(
        "toplam_tiklama", "Toplam Tıklama", MetricUnit.ADET, lambda _: pl.col("tiklama").sum()
    ),
    Aggregate(
        "toplam_gosterim", "Toplam Gösterim", MetricUnit.ADET, lambda _: pl.col("gosterim").sum()
    ),
    Aggregate(
        "ortalama_frekans", "Ortalama Frekans", MetricUnit.ORAN, lambda _: pl.col("frekans").mean()
    ),
)


ENTITY_AGGREGATES = (
    Aggregate(
        "toplam_harcama_tl", "Toplam Harcama", MetricUnit.TL, lambda _: pl.col("harcama_tl").sum()
    ),
    Aggregate("toplam_gelir_tl", "Toplam Gelir", MetricUnit.TL, lambda _: pl.col("gelir_tl").sum()),
    Aggregate(
        "toplam_donusum", "Toplam Dönüşüm", MetricUnit.ADET, lambda _: pl.col("donusum").sum()
    ),
    Aggregate(
        "toplam_roas",
        "Dönem Geneli ROAS",
        MetricUnit.ORAN,
        lambda _: _safe_ratio(pl.col("gelir_tl").sum(), pl.col("harcama_tl").sum()),
    ),
    Aggregate("son_roas", "Son ROAS", MetricUnit.ORAN, lambda _: pl.col("roas").last()),
    Aggregate("ilk_roas", "İlk ROAS", MetricUnit.ORAN, lambda _: pl.col("roas").first()),
    Aggregate(
        "roas_degisim_yuzde",
        "ROAS Değişimi",
        MetricUnit.YUZDE,
        lambda _: pl.when(pl.col("roas").first() > 0)
        .then((pl.col("roas").last() - pl.col("roas").first()) / pl.col("roas").first() * 100)
        .otherwise(None),
    ),
    Aggregate(
        "son_harcama_tl", "Son Dönem Harcama", MetricUnit.TL, lambda _: pl.col("harcama_tl").last()
    ),
    Aggregate(
        "ilk_harcama_tl", "İlk Dönem Harcama", MetricUnit.TL, lambda _: pl.col("harcama_tl").first()
    ),
    Aggregate(
        "harcama_degisim_yuzde",
        "Harcama Değişimi",
        MetricUnit.YUZDE,
        lambda _: pl.when(pl.col("harcama_tl").first() > 0)
        .then(
            (pl.col("harcama_tl").last() - pl.col("harcama_tl").first())
            / pl.col("harcama_tl").first()
            * 100
        )
        .otherwise(None),
    ),
    Aggregate("son_frekans", "Son Frekans", MetricUnit.ORAN, lambda _: pl.col("frekans").last()),
    Aggregate("ilk_frekans", "İlk Frekans", MetricUnit.ORAN, lambda _: pl.col("frekans").first()),
    Aggregate(
        "frekans_degisim",
        "Frekans Değişimi",
        MetricUnit.ORAN,
        lambda _: pl.col("frekans").last() - pl.col("frekans").first(),
    ),
    Aggregate("son_ctr", "Son CTR", MetricUnit.YUZDE, lambda _: pl.col("ctr").last()),
    Aggregate("ilk_ctr", "İlk CTR", MetricUnit.YUZDE, lambda _: pl.col("ctr").first()),
    Aggregate(
        "ctr_degisim_puan",
        "CTR Değişimi",
        MetricUnit.YUZDE,
        lambda _: pl.col("ctr").last() - pl.col("ctr").first(),
    ),
    Aggregate("son_cpa", "Son CPA", MetricUnit.TL, lambda _: pl.col("cpa").last()),
    Aggregate("ilk_cpa", "İlk CPA", MetricUnit.TL, lambda _: pl.col("cpa").first()),
    Aggregate("son_cvr", "Son Dönüşüm Oranı", MetricUnit.YUZDE, lambda _: pl.col("cvr").last()),
    Aggregate("net_katki_tl", "Net Katkı", MetricUnit.TL, lambda _: pl.col("net_kar_tl").sum()),
    Aggregate(
        "zarardaki_donem",
        "Zararda Geçen Dönem",
        MetricUnit.SAYI,
        lambda _: (pl.col("roas") < ROAS_ZARAR).sum(),
    ),
    Aggregate(
        "doyum_donemi",
        "Frekansın Doyuma Ulaştığı Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key).filter(pl.col("frekans") >= FREKANS_DOYUM).first(),
        internal=True,
    ),
    Aggregate(
        "zarar_donemi",
        "Zarara Geçilen Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key).filter(pl.col("roas") < ROAS_ZARAR).first(),
        internal=True,
    ),
    Aggregate(
        "harcama_trend_step",
        "Harcama Eğilimi (Dönem Başı)",
        MetricUnit.TL,
        lambda _: pl.when(pl.len() > 1)
        .then((pl.col("harcama_tl").last() - pl.col("harcama_tl").first()) / (pl.len() - 1))
        .otherwise(0.0),
    ),
)


DIMENSION_AGGREGATES = (
    Aggregate("toplam_harcama_tl", "Harcama", MetricUnit.TL, lambda _: pl.col("harcama_tl").sum()),
    Aggregate("toplam_gelir_tl", "Gelir", MetricUnit.TL, lambda _: pl.col("gelir_tl").sum()),
    Aggregate(
        "portfoy_roas",
        "ROAS",
        MetricUnit.ORAN,
        lambda _: _safe_ratio(pl.col("gelir_tl").sum(), pl.col("harcama_tl").sum()),
    ),
    Aggregate("toplam_donusum", "Dönüşüm", MetricUnit.ADET, lambda _: pl.col("donusum").sum()),
    Aggregate(
        "kampanya_sayisi",
        "Kampanya Sayısı",
        MetricUnit.SAYI,
        lambda _: pl.col("kampanya_id").n_unique(),
    ),
)


RISK_RULES = (
    RiskRule(
        code="AD_FATIGUE",
        title="Kitle yorulması -- kreatif tükendi",
        severity=Severity.KRITIK,
        predicate=lambda _: (pl.col("frekans_degisim") > 0.5)
        & (pl.col("ctr_degisim_puan") < 0)
        & (pl.col("roas_degisim_yuzde") < ROAS_DUSUS_YUZDE),
        narrative=lambda row: (
            f"Frekans {_num(row, 'ilk_frekans'):.1f}'den {_num(row, 'son_frekans'):.1f}'e çıktı: "
            "aynı kişilere tekrar tekrar gösteriliyor. Aynı dönemde CTR "
            f"%{_num(row, 'ilk_ctr'):.2f}'den %{_num(row, 'son_ctr'):.2f}'e, ROAS "
            f"{_num(row, 'ilk_roas'):.2f}'den {_num(row, 'son_roas'):.2f}'e düştü. "
            "Harcama artmaya devam ederken sonuç düşüyor -- kitle doydu."
        ),
        recommendation=(
            "Kampanyayı durdurun. Kreatifi yenileyip kitleyi genişletmeden bütçe "
            "koymayın; mevcut haliyle her ek lira daha az geri dönüyor."
        ),
        evidence_metrics=(
            "ilk_frekans",
            "son_frekans",
            "ilk_ctr",
            "son_ctr",
            "ilk_roas",
            "son_roas",
            "son_harcama_tl",
        ),
        impact=lambda row: _num(row, "son_harcama_tl") * max(0.0, 1 - _num(row, "son_roas")),
        first_seen=lambda row: str(row.get("doyum_donemi")) if row.get("doyum_donemi") else None,
    ),
    RiskRule(
        code="SCALING_INEFFICIENCY",
        title="Verimsiz ölçekleme -- bütçe artıyor, getiri düşüyor",
        severity=Severity.KRITIK,
        predicate=lambda _: (pl.col("harcama_degisim_yuzde") > HARCAMA_ARTIS_YUZDE)
        & (pl.col("roas_degisim_yuzde") < ROAS_DUSUS_YUZDE),
        narrative=lambda row: (
            f"Harcama {_tl(_num(row, 'ilk_harcama_tl'))} seviyesinden "
            f"{_tl(_num(row, 'son_harcama_tl'))} seviyesine çıktı "
            f"(%{_num(row, 'harcama_degisim_yuzde'):.0f} artış) ama ROAS "
            f"{_num(row, 'ilk_roas'):.2f}'den {_num(row, 'son_roas'):.2f}'e geriledi. "
            "Bütçe büyüdükçe verim düşüyor: kampanya ölçeklenmeye uygun değil."
        ),
        recommendation=(
            "Bütçeyi ölçekleme öncesi seviyeye çekin. Ek bütçeyi ROAS'ı yüksek "
            "kampanyalara aktarın."
        ),
        evidence_metrics=(
            "ilk_harcama_tl",
            "son_harcama_tl",
            "harcama_degisim_yuzde",
            "ilk_roas",
            "son_roas",
            "son_cpa",
        ),
        impact=lambda row: max(0.0, _num(row, "son_harcama_tl") - _num(row, "ilk_harcama_tl")),
        first_seen=lambda row: str(row.get("zarar_donemi")) if row.get("zarar_donemi") else None,
    ),
    RiskRule(
        code="UNPROFITABLE",
        title="Kampanya para kaybediyor",
        severity=Severity.KRITIK,
        predicate=lambda _: pl.col("son_roas") < ROAS_ZARAR,
        narrative=lambda row: (
            f"Son dönem ROAS {_num(row, 'son_roas'):.2f}: harcanan her 1 TL "
            f"{_num(row, 'son_roas'):.2f} TL geri getiriyor. Altı dönemde toplam net "
            f"katkı {_tl(_num(row, 'net_katki_tl'))}."
        ),
        recommendation=(
            "Durdurun ya da hedefleme/kreatif tamamen yenilenene kadar bütçeyi " "minimuma çekin."
        ),
        evidence_metrics=("son_roas", "net_katki_tl", "son_harcama_tl", "zarardaki_donem"),
        impact=lambda row: abs(min(0.0, _num(row, "net_katki_tl"))),
        first_seen=lambda row: str(row.get("zarar_donemi")) if row.get("zarar_donemi") else None,
    ),
    RiskRule(
        code="STAR_SCALE_UP",
        title="Yıldız kampanya -- bütçe artırılmalı",
        severity=Severity.YUKSEK,
        predicate=lambda _: (pl.col("son_roas") > ROAS_YILDIZ)
        & (pl.col("son_frekans") < FREKANS_DOYUM),
        narrative=lambda row: (
            f"ROAS {_num(row, 'son_roas'):.2f} ve frekans {_num(row, 'son_frekans'):.1f} -- "
            "kitle henüz doymamış. Bu kampanya ek bütçeyi verimli çevirebilecek "
            f"durumda; şu an aylık {_tl(_num(row, 'son_harcama_tl'))} harcıyor."
        ),
        recommendation=(
            "Bütçeyi kademeli artırın (%20-30 adımlarla) ve her adımda ROAS ile "
            "frekansı izleyin."
        ),
        evidence_metrics=("son_roas", "son_frekans", "son_harcama_tl", "son_cvr", "net_katki_tl"),
        impact=lambda row: _num(row, "son_harcama_tl") * 0.3 * (_num(row, "son_roas") - 1),
        first_seen=None,
    ),
    RiskRule(
        code="FREQUENCY_SATURATION",
        title="Frekans doyum eşiğinde",
        severity=Severity.ORTA,
        predicate=lambda _: (pl.col("son_frekans") >= FREKANS_DOYUM)
        & (pl.col("roas_degisim_yuzde") >= ROAS_DUSUS_YUZDE),
        narrative=lambda row: (
            f"Frekans {_num(row, 'son_frekans'):.1f}'e ulaştı. ROAS henüz sert düşmedi "
            "ama aynı kitleye tekrar gösterim artıyor; önlem alınmazsa yorulma başlar."
        ),
        recommendation="Kitleyi genişletin veya kreatif rotasyonu kurun.",
        evidence_metrics=("son_frekans", "frekans_degisim", "son_roas", "son_ctr"),
        impact=None,
        first_seen=lambda row: str(row.get("doyum_donemi")) if row.get("doyum_donemi") else None,
    ),
    RiskRule(
        code="EFFICIENT_GROWTH",
        title="Verimli büyüme -- ölçekleme çalışıyor",
        severity=Severity.BILGI,
        predicate=lambda _: (pl.col("harcama_degisim_yuzde") > HARCAMA_ARTIS_YUZDE)
        & (pl.col("roas_degisim_yuzde") > -10.0)
        & (pl.col("son_roas") > ROAS_ZARAR),
        narrative=lambda row: (
            f"Harcama %{_num(row, 'harcama_degisim_yuzde'):.0f} arttığı halde ROAS "
            f"{_num(row, 'ilk_roas'):.2f} -> {_num(row, 'son_roas'):.2f} seviyesinde korundu. "
            "Ölçekleme verimi bozmadı; mevsimsel talep gerçek."
        ),
        recommendation="Bu kampanyaya bütçe aktarımı güvenli; artışı sürdürün.",
        evidence_metrics=("harcama_degisim_yuzde", "ilk_roas", "son_roas", "toplam_gelir_tl"),
        impact=None,
        first_seen=None,
    ),
    RiskRule(
        code="LOW_CONVERSION",
        title="Düşük dönüşüm oranı",
        severity=Severity.ORTA,
        predicate=lambda _: (pl.col("son_cvr") < 2.0) & (pl.col("son_roas") < ROAS_YILDIZ),
        narrative=lambda row: (
            f"Dönüşüm oranı %{_num(row, 'son_cvr'):.2f}: tıklama geliyor ama satışa "
            f"dönmüyor. CPA {_tl(_num(row, 'son_cpa'))}."
        ),
        recommendation=(
            "Landing sayfası ve ürün-kitle uyumunu gözden geçirin; sorun reklamda " "olmayabilir."
        ),
        evidence_metrics=("son_cvr", "son_cpa", "son_roas"),
        impact=None,
        first_seen=None,
    ),
)


PROMPT_PROFILE = PromptProfile(
    persona=(
        "E-ticaret performans pazarlamasında uzmanlaşmış, Meta/Instagram medya "
        "planlamasi yapan bir danismansin."
    ),
    domain_label="Meta/Instagram reklam performans raporu",
    entity_noun="kampanya",
    entity_noun_plural="kampanyalar",
    departments=(
        Department("medya_alimi", "Medya Alımı"),
        Department("kreatif", "Kreatif"),
        Department("e_ticaret", "E-ticaret"),
        Department("finans", "Finans"),
    ),
    kpi_glossary={
        "roas": "Gelir / harcama. 1'in altında kampanya para kaybediyor demektir.",
        "frekans": "Aynı kişinin reklamı kaç kez gördüğü. 2.5 üstü kitle yorulması sinyali.",
        "ctr": "Tıklama / gösterim. Kreatifin ilgi çekiciliği.",
        "cvr": "Dönüşüm / tıklama. Tıklamanın satışa dönme oranı.",
        "cpa": "Dönüşüm başı maliyet.",
        "net_katki_tl": "Gelir eksi harcama; kampanyanın net parasal katkısı.",
    },
    dynamics=(
        "mevsimsellik",
        "kitle_yorulmasi",
        "olcekleme_verimi",
        "kreatif_performansi",
        "butce_tahsisi",
        "donusum_darbogazi",
    ),
    action_style=(
        "Aksiyonlar bütçe diliyle konuşmalı: hangi kampanyadan ne kadar çekilip "
        "nereye aktarılacağı net olmalı. 'Performansı iyileştirin' gibi ifadeler kullanma."
    ),
)


PACK = DatasetPack(
    key="zewnos-ads",
    title="Zewnos -- Meta/Instagram Reklam Performansı",
    description=(
        "Kampanya bazında dönemsel reklam performansı: harcama, gösterim, tıklama, "
        "frekans, dönüşüm ve gelir."
    ),
    entity_key="kampanya_id",
    entity_label_key="kampanya_adi",
    period_key="donem",
    dimensions=("urun_kategorisi", "platform"),
    columns=COLUMNS,
    derived_metrics=DERIVED_METRICS,
    integrity_rules=INTEGRITY_RULES,
    imputation_rules=IMPUTATION_RULES,
    risk_rules=RISK_RULES,
    period_aggregates=PERIOD_AGGREGATES,
    entity_aggregates=ENTITY_AGGREGATES,
    dimension_aggregates=DIMENSION_AGGREGATES,
    prompt_profile=PROMPT_PROFILE,
    entity_trend_column="harcama_tl",
    snapshot_columns=(
        "harcama_tl",
        "gelir_tl",
        "roas",
        "frekans",
        "ctr",
        "cvr",
        "donusum",
    ),
    sample_file="zewnos_meta_ads_cok_donemli.csv",
)
