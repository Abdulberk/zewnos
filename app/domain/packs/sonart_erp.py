"""Sonart Tekstil -- ERP stok/satis raporu pack'i.

Logo Netsis'ten alinan donemsel stok hareket raporunun tanimi. Motor bu
dosyayi okuyarak ne hesaplayacagini ve neyi risk sayacagini ogrenir.

Kaynak kolonlar:
    stok_kodu, urun_adi, kategori, depo, donem,
    giris_miktar, cikis_miktar, donem_sonu_stok,
    birim_maliyet_tl, birim_satis_tl
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
    PackContext,
    PromptProfile,
    RiskRule,
    RowMapping,
)

# --- esikler (tek yerde, aciklanabilir olsun diye) --------------------------
KAPAMA_KRITIK_AY = 1.5  # bunun altinda stok tukenmesi yakin
KAPAMA_YAVAS_AY = 6.0  # bunun ustunde yavas hareket
KAPAMA_OLU_AY = 12.0  # bunun ustunde olu stok
MARJ_EROZYON_PUAN = 5.0  # yuzde puan cinsinden dusus esigi
MALIYET_SOK_YUZDE = 10.0  # donemsel birim maliyet siçramasi
TALEP_PATLAMASI_KAT = 1.5  # son3 / ilk3 cikis orani


def _num(row: RowMapping, key: str, default: float = 0.0) -> float:
    value = row.get(key)
    return float(value) if value is not None else default


def _tl(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") + " TL"


# ---------------------------------------------------------------------------
# Kolonlar
# ---------------------------------------------------------------------------
COLUMNS = (
    ColumnDef("stok_kodu", ("stok kodu", "urun_kodu", "sku"), ColumnType.METIN, True, "Stok Kodu"),
    ColumnDef("urun_adi", ("urun adi", "malzeme_adi"), ColumnType.METIN, True, "Ürün Adı"),
    ColumnDef("kategori", ("urun_kategorisi",), ColumnType.METIN, True, "Kategori"),
    ColumnDef("depo", ("depo_adi", "ambar"), ColumnType.METIN, True, "Depo"),
    ColumnDef("donem", ("period", "ay", "donem_kodu"), ColumnType.DONEM, True, "Dönem"),
    ColumnDef(
        "giris_miktar",
        ("giris", "giris_miktari"),
        ColumnType.ONDALIK,
        True,
        "Giriş",
        MetricUnit.ADET,
    ),
    ColumnDef(
        "cikis_miktar",
        ("cikis", "cikis_miktari"),
        ColumnType.ONDALIK,
        True,
        "Çıkış",
        MetricUnit.ADET,
    ),
    ColumnDef(
        "donem_sonu_stok",
        ("son_stok", "kalan_stok"),
        ColumnType.ONDALIK,
        True,
        "Dönem Sonu Stok",
        MetricUnit.ADET,
    ),
    ColumnDef(
        "birim_maliyet_tl",
        ("birim_maliyet", "maliyet"),
        ColumnType.ONDALIK,
        True,
        "Birim Maliyet",
        MetricUnit.TL,
    ),
    ColumnDef(
        "birim_satis_tl",
        ("birim_satis", "satis_fiyati"),
        ColumnType.ONDALIK,
        True,
        "Birim Satış Fiyatı",
        MetricUnit.TL,
    ),
)


# ---------------------------------------------------------------------------
# Turetilmis metrikler
# ---------------------------------------------------------------------------
def _kapama_ay(_: PackContext) -> pl.Expr:
    """Mevcut stok kac ay yeter? (son 3 donemin ortalama cikisina gore)

    Tek donemlik cikisa bolmek gurultuye acik; 3 donemlik hareketli ortalama
    mevsimsel dalgalanmayi yumusatiyor.
    """
    ort = pl.col("cikis_ort3")
    return pl.when(ort > 0).then(pl.col("donem_sonu_stok") / ort).otherwise(None).alias("kapama_ay")


DERIVED_METRICS = (
    # --- satir ici ---
    DerivedMetric(
        "ciro_tl",
        "Ciro",
        MetricUnit.TL,
        lambda _: pl.col("cikis_miktar") * pl.col("birim_satis_tl"),
        "row",
        "Dönemsel satış geliri (çıkış x birim satış fiyatı).",
    ),
    DerivedMetric(
        "satis_maliyeti_tl",
        "Satış Maliyeti",
        MetricUnit.TL,
        lambda _: pl.col("cikis_miktar") * pl.col("birim_maliyet_tl"),
        "row",
    ),
    DerivedMetric(
        "brut_kar_tl",
        "Brüt Kâr",
        MetricUnit.TL,
        lambda _: pl.col("cikis_miktar") * (pl.col("birim_satis_tl") - pl.col("birim_maliyet_tl")),
        "row",
    ),
    DerivedMetric(
        "marj_yuzde",
        "Brüt Marj",
        MetricUnit.YUZDE,
        lambda _: pl.when(pl.col("birim_satis_tl") > 0)
        .then(
            (pl.col("birim_satis_tl") - pl.col("birim_maliyet_tl")) / pl.col("birim_satis_tl") * 100
        )
        .otherwise(None),
        "row",
        "Birim bazında brüt kâr yüzdesi.",
    ),
    DerivedMetric(
        "stok_degeri_tl",
        "Stok Değeri",
        MetricUnit.TL,
        lambda _: pl.col("donem_sonu_stok") * pl.col("birim_maliyet_tl"),
        "row",
        "Dönem sonunda depoda bağlı sermaye.",
    ),
    DerivedMetric(
        "net_akis",
        "Net Stok Akışı",
        MetricUnit.ADET,
        lambda _: pl.col("giris_miktar") - pl.col("cikis_miktar"),
        "row",
    ),
    # --- pencere (entity bazli) ---
    DerivedMetric(
        "onceki_stok",
        "Önceki Dönem Stoğu",
        MetricUnit.ADET,
        lambda ctx: pl.col("donem_sonu_stok").shift(1).over(ctx.entity_key),
        "window",
    ),
    DerivedMetric(
        "cikis_ort3",
        "Çıkış (3 Dönem Ort.)",
        MetricUnit.ADET,
        lambda ctx: pl.col("cikis_miktar")
        .rolling_mean(window_size=3, min_periods=1)
        .over(ctx.entity_key),
        "window",
    ),
    DerivedMetric(
        "cikis_mom_yuzde",
        "Çıkış Değişimi (Aylık)",
        MetricUnit.YUZDE,
        lambda ctx: (pl.col("cikis_miktar").pct_change().over(ctx.entity_key) * 100),
        "window",
    ),
    DerivedMetric(
        "maliyet_mom_yuzde",
        "Birim Maliyet Değişimi (Aylık)",
        MetricUnit.YUZDE,
        lambda ctx: (pl.col("birim_maliyet_tl").pct_change().over(ctx.entity_key) * 100),
        "window",
    ),
    DerivedMetric(
        "marj_delta_puan",
        "Marj Değişimi (Puan)",
        MetricUnit.YUZDE,
        lambda ctx: pl.col("marj_yuzde") - pl.col("marj_yuzde").shift(1).over(ctx.entity_key),
        "window",
    ),
    DerivedMetric("kapama_ay", "Stok Kapama Süresi", MetricUnit.AY, _kapama_ay, "window"),
    DerivedMetric(
        "mutabakat_farki",
        "Stok Mutabakat Farkı",
        MetricUnit.ADET,
        lambda ctx: pl.col("donem_sonu_stok")
        - (
            pl.col("donem_sonu_stok").shift(1).over(ctx.entity_key)
            + pl.col("giris_miktar")
            - pl.col("cikis_miktar")
        ),
        "window",
        "Beklenen dönem sonu stoğu ile raporlanan arasındaki fark.",
    ),
    DerivedMetric(
        "arz_kisitli",
        "Arz Kısıtlı",
        MetricUnit.SAYI,
        lambda _: (
            (pl.col("donem_sonu_stok") <= 0) & (pl.col("cikis_miktar") <= pl.col("giris_miktar"))
        ).cast(pl.Int8),
        "row",
        "Stok sıfır ve çıkış girişe kilitli: satış talep değil, tedarik belirliyor.",
    ),
)


# ---------------------------------------------------------------------------
# Eksik deger tamamlama
# ---------------------------------------------------------------------------
IMPUTATION_RULES = (
    ImputationRule(
        code="IMPUTED_FLOW",
        title="Eksik giriş/çıkış miktarları ürünün kendi ortancasından tamamlandı",
        target_column="giris_miktar",
        forward=lambda ctx: pl.col("giris_miktar").median().over(ctx.entity_key),
        detail=(
            "Eksik giriş miktarı, aynı ürünün diğer dönemlerindeki ortanca değerle "
            "dolduruldu. Ortalama yerine ortanca: tek bir uç değer tahmini bozmasın."
        ),
    ),
    ImputationRule(
        code="IMPUTED_FLOW",
        title="Eksik çıkış miktarları ürünün kendi ortancasından tamamlandı",
        target_column="cikis_miktar",
        forward=lambda ctx: pl.col("cikis_miktar").median().over(ctx.entity_key),
        detail="Eksik çıkış miktarı aynı ürünün dönemler arası ortanca değeriyle dolduruldu.",
    ),
    ImputationRule(
        code="IMPUTED_STOCK",
        title="Eksik dönem sonu stoğu mutabakattan türetildi",
        target_column="donem_sonu_stok",
        # ileri: onceki donem sonu + giris - cikis
        forward=lambda ctx: (
            pl.col("donem_sonu_stok").shift(1).over(ctx.entity_key)
            + pl.col("giris_miktar")
            - pl.col("cikis_miktar")
        ),
        # geri: sonraki donem sonu - sonraki giris + sonraki cikis
        backward=lambda ctx: (
            pl.col("donem_sonu_stok").shift(-1).over(ctx.entity_key)
            - pl.col("giris_miktar").shift(-1).over(ctx.entity_key)
            + pl.col("cikis_miktar").shift(-1).over(ctx.entity_key)
        ),
        detail=(
            "Boş bırakılan dönem sonu stoğu, stok mutabakatı denkleminden hesaplandı: "
            "önceki dönem sonu + giriş - çıkış. Aynı değer bir de sonraki dönemden "
            "geriye doğru doğrulandı."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Butunluk kurallari
# ---------------------------------------------------------------------------
INTEGRITY_RULES = (
    IntegrityRule(
        code="RECONCILIATION_BREAK",
        title="Stok mutabakatı tutmuyor",
        severity=Severity.YUKSEK,
        action=IssueAction.ISARETLENDI,
        violation=lambda ctx: (
            pl.col("onceki_stok").is_not_null() & (pl.col("mutabakat_farki").abs() > 0.5)
        ),
        detail_template=(
            "{count} kayıtta 'önceki dönem sonu + giriş - çıkış' hesabı raporlanan "
            "dönem sonu stoğuyla örtüşmüyor. Kaynak sistemde sayım düzeltmesi, fire "
            "veya kayıt atlaması olabilir."
        ),
        sample_columns=("stok_kodu", "donem", "mutabakat_farki"),
    ),
    IntegrityRule(
        code="NEGATIVE_VALUE",
        title="Negatif miktar",
        severity=Severity.KRITIK,
        action=IssueAction.ISARETLENDI,
        violation=lambda _: (
            (pl.col("giris_miktar") < 0)
            | (pl.col("cikis_miktar") < 0)
            | (pl.col("donem_sonu_stok") < 0)
        ),
        detail_template="{count} kayıtta negatif miktar var; fiziksel olarak mümkün değil.",
        sample_columns=("stok_kodu", "donem", "donem_sonu_stok"),
    ),
    IntegrityRule(
        code="MARGIN_INVERSION",
        title="Maliyet satış fiyatına eşit ya da üstünde",
        severity=Severity.KRITIK,
        action=IssueAction.ISARETLENDI,
        violation=lambda _: pl.col("birim_maliyet_tl") >= pl.col("birim_satis_tl"),
        detail_template="{count} kayıtta ürün maliyetine eşit ya da altında satılıyor.",
        sample_columns=("stok_kodu", "donem", "birim_maliyet_tl", "birim_satis_tl"),
    ),
    IntegrityRule(
        code="COST_SPIKE",
        title="Birim maliyette ani sıçrama",
        severity=Severity.ORTA,
        action=IssueAction.ISARETLENDI,
        violation=lambda _: pl.col("maliyet_mom_yuzde") > MALIYET_SOK_YUZDE,
        detail_template=(
            f"{{count}} kayıtta birim maliyet bir önceki döneme göre %{MALIYET_SOK_YUZDE:.0f} "
            "üzerinde arttı. Tedarikçi fiyat güncellemesi veya kur etkisi olabilir; "
            "satış fiyatı aynı kaldıysa marj doğrudan eriyor."
        ),
        sample_columns=("stok_kodu", "donem", "maliyet_mom_yuzde"),
    ),
)


# ---------------------------------------------------------------------------
# Toplulastirmalar
# ---------------------------------------------------------------------------
PERIOD_AGGREGATES = (
    Aggregate(
        "toplam_ciro_tl", "Toplam Ciro", MetricUnit.TL, lambda _: pl.col("ciro_tl").sum(), True
    ),
    Aggregate(
        "toplam_brut_kar_tl",
        "Brüt Kâr",
        MetricUnit.TL,
        lambda _: pl.col("brut_kar_tl").sum(),
        True,
    ),
    Aggregate(
        "ortalama_marj_yuzde",
        "Ağırlıklı Marj",
        MetricUnit.YUZDE,
        lambda _: pl.when(pl.col("ciro_tl").sum() > 0)
        .then(pl.col("brut_kar_tl").sum() / pl.col("ciro_tl").sum() * 100)
        .otherwise(None),
        True,
    ),
    Aggregate(
        "toplam_stok_degeri_tl",
        "Stokta Bağlı Sermaye",
        MetricUnit.TL,
        lambda _: pl.col("stok_degeri_tl").sum(),
        True,
    ),
    Aggregate(
        "tukenen_urun_sayisi",
        "Stoğu Tükenen Ürün",
        MetricUnit.SAYI,
        lambda _: (pl.col("donem_sonu_stok") <= 0).sum(),
        True,
    ),
    Aggregate(
        "toplam_cikis", "Toplam Çıkış", MetricUnit.ADET, lambda _: pl.col("cikis_miktar").sum()
    ),
    Aggregate(
        "toplam_giris", "Toplam Giriş", MetricUnit.ADET, lambda _: pl.col("giris_miktar").sum()
    ),
    Aggregate(
        "toplam_stok_adet",
        "Toplam Stok",
        MetricUnit.ADET,
        lambda _: pl.col("donem_sonu_stok").sum(),
    ),
)


ENTITY_AGGREGATES = (
    Aggregate("toplam_ciro_tl", "Toplam Ciro", MetricUnit.TL, lambda _: pl.col("ciro_tl").sum()),
    Aggregate(
        "toplam_brut_kar_tl", "Brüt Kâr", MetricUnit.TL, lambda _: pl.col("brut_kar_tl").sum()
    ),
    Aggregate("son_stok", "Son Stok", MetricUnit.ADET, lambda _: pl.col("donem_sonu_stok").last()),
    Aggregate("ilk_stok", "İlk Stok", MetricUnit.ADET, lambda _: pl.col("donem_sonu_stok").first()),
    Aggregate("son_kapama_ay", "Stok Kapama", MetricUnit.AY, lambda _: pl.col("kapama_ay").last()),
    Aggregate(
        "son_marj_yuzde", "Son Marj", MetricUnit.YUZDE, lambda _: pl.col("marj_yuzde").last()
    ),
    Aggregate(
        "ilk_marj_yuzde", "İlk Marj", MetricUnit.YUZDE, lambda _: pl.col("marj_yuzde").first()
    ),
    Aggregate(
        "marj_degisim_puan",
        "Marj Değişimi",
        MetricUnit.YUZDE,
        lambda _: pl.col("marj_yuzde").last() - pl.col("marj_yuzde").first(),
    ),
    Aggregate(
        "son_birim_maliyet",
        "Son Birim Maliyet",
        MetricUnit.TL,
        lambda _: pl.col("birim_maliyet_tl").last(),
    ),
    Aggregate(
        "maliyet_degisim_yuzde",
        "Maliyet Değişimi",
        MetricUnit.YUZDE,
        lambda _: pl.when(pl.col("birim_maliyet_tl").first() > 0)
        .then(
            (pl.col("birim_maliyet_tl").last() - pl.col("birim_maliyet_tl").first())
            / pl.col("birim_maliyet_tl").first()
            * 100
        )
        .otherwise(None),
    ),
    Aggregate(
        "son_birim_satis",
        "Son Satış Fiyatı",
        MetricUnit.TL,
        lambda _: pl.col("birim_satis_tl").last(),
    ),
    Aggregate(
        "son_stok_degeri_tl",
        "Bağlı Sermaye",
        MetricUnit.TL,
        lambda _: pl.col("stok_degeri_tl").last(),
    ),
    Aggregate(
        "sifir_stok_donem",
        "Stoksuz Dönem Sayısı",
        MetricUnit.SAYI,
        lambda _: (pl.col("donem_sonu_stok") <= 0).sum(),
    ),
    Aggregate(
        "ilk_sifir_donem",
        "İlk Stoksuz Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key).filter(pl.col("donem_sonu_stok") <= 0).first(),
        internal=True,
    ),
    Aggregate(
        "arz_kisitli_donem",
        "Arz Kısıtlı Dönem",
        MetricUnit.SAYI,
        lambda _: pl.col("arz_kisitli").sum(),
    ),
    Aggregate(
        "ilk_cikis", "İlk Dönem Çıkış", MetricUnit.ADET, lambda _: pl.col("cikis_miktar").first()
    ),
    Aggregate(
        "son_cikis", "Son Dönem Çıkış", MetricUnit.ADET, lambda _: pl.col("cikis_miktar").last()
    ),
    Aggregate(
        "ortalama_cikis", "Ortalama Çıkış", MetricUnit.ADET, lambda _: pl.col("cikis_miktar").mean()
    ),
    Aggregate(
        "ilk3_cikis_ort",
        "İlk 3 Dönem Ort. Çıkış",
        MetricUnit.ADET,
        lambda _: pl.col("cikis_miktar").head(3).mean(),
    ),
    Aggregate(
        "son3_cikis_ort",
        "Son 3 Dönem Ort. Çıkış",
        MetricUnit.ADET,
        lambda _: pl.col("cikis_miktar").tail(3).mean(),
    ),
    Aggregate(
        "zirve_cikis", "Zirve Çıkış", MetricUnit.ADET, lambda _: pl.col("cikis_miktar").max()
    ),
    Aggregate(
        "zirve_donem",
        "Zirve Dönemi",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key).sort_by("cikis_miktar", descending=True).first(),
        internal=True,
    ),
    Aggregate(
        "net_akis_toplam", "Net Stok Akışı", MetricUnit.ADET, lambda _: pl.col("net_akis").sum()
    ),
    Aggregate(
        "stok_trend_step",
        "Stok Eğilimi (Dönem Başı)",
        MetricUnit.ADET,
        lambda _: pl.when(pl.len() > 1)
        .then(
            (pl.col("donem_sonu_stok").last() - pl.col("donem_sonu_stok").first()) / (pl.len() - 1)
        )
        .otherwise(0.0),
    ),
    Aggregate(
        "cikis_trend_step",
        "Çıkış Eğilimi (Dönem Başı)",
        MetricUnit.ADET,
        lambda _: pl.when(pl.len() > 1)
        .then((pl.col("cikis_miktar").last() - pl.col("cikis_miktar").first()) / (pl.len() - 1))
        .otherwise(0.0),
    ),
    # --- risklerin "ne zaman basladi" bilgisi -------------------------------
    # Entity seviyesindeki riskler tum seriye bakarak hesaplanir; tek basina
    # bir donemleri yoktur. Bu alanlar riskin *ilk goruldugu* donemi bulur,
    # boylece dashboard "bu ay hangi risk ortaya cikti" diyebilir.
    Aggregate(
        "maliyet_sok_donem",
        "Maliyet Şokunun Yaşandığı Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key)
        .filter(pl.col("maliyet_mom_yuzde") > MALIYET_SOK_YUZDE)
        .first(),
        internal=True,
    ),
    Aggregate(
        "marj_dusus_donem",
        "Marjın Düştüğü Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key).filter(pl.col("marj_delta_puan") < -3.0).first(),
        internal=True,
    ),
    Aggregate(
        "kritik_kapama_donem",
        "Kritik Kapamaya Düşülen Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key)
        .filter((pl.col("kapama_ay") < KAPAMA_KRITIK_AY) & (pl.col("donem_sonu_stok") > 0))
        .first(),
        internal=True,
    ),
    Aggregate(
        "olu_stok_donem",
        "Ölü Stoğa Geçilen Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key).filter(pl.col("kapama_ay") > KAPAMA_OLU_AY).first(),
        internal=True,
    ),
    Aggregate(
        "yavas_donem",
        "Yavaşlamanın Başladığı Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key).filter(pl.col("kapama_ay") >= KAPAMA_YAVAS_AY).first(),
        internal=True,
    ),
    Aggregate(
        "talep_patlama_donem",
        "Talebin Hızlandığı Dönem",
        MetricUnit.SAYI,
        lambda ctx: pl.col(ctx.period_key)
        .filter(
            pl.col("cikis_miktar") > pl.col("cikis_miktar").head(3).mean() * TALEP_PATLAMASI_KAT
        )
        .first(),
        internal=True,
    ),
)


DIMENSION_AGGREGATES = (
    Aggregate("toplam_ciro_tl", "Ciro", MetricUnit.TL, lambda _: pl.col("ciro_tl").sum()),
    Aggregate(
        "toplam_brut_kar_tl", "Brüt Kâr", MetricUnit.TL, lambda _: pl.col("brut_kar_tl").sum()
    ),
    Aggregate(
        "ortalama_marj_yuzde",
        "Marj",
        MetricUnit.YUZDE,
        lambda _: pl.when(pl.col("ciro_tl").sum() > 0)
        .then(pl.col("brut_kar_tl").sum() / pl.col("ciro_tl").sum() * 100)
        .otherwise(None),
    ),
    Aggregate(
        "toplam_stok_degeri_tl",
        "Stok Değeri",
        MetricUnit.TL,
        lambda _: pl.col("stok_degeri_tl").sum(),
    ),
    Aggregate("toplam_cikis", "Çıkış", MetricUnit.ADET, lambda _: pl.col("cikis_miktar").sum()),
    Aggregate(
        "urun_sayisi", "Ürün Sayısı", MetricUnit.SAYI, lambda _: pl.col("stok_kodu").n_unique()
    ),
)


# ---------------------------------------------------------------------------
# Risk kurallari
# ---------------------------------------------------------------------------
def _stockout_narrative(row: RowMapping) -> str:
    donem = int(_num(row, "sifir_stok_donem"))
    kisitli = int(_num(row, "arz_kisitli_donem"))
    ilk = row.get("ilk_cikis")
    son = row.get("son_cikis")
    metin = (
        f"{donem} dönemdir stok sıfır. Bu dönemlerin {kisitli} tanesinde çıkış "
        "girişe kilitlenmiş durumda -- yani satışı talep değil tedarik belirliyor."
    )
    if ilk and son and ilk > son:
        metin += (
            f" Tükenmeden önceki dönemsel çıkış {ilk:.0f} adetken şimdi {son:.0f} adete "
            "düşmüş; aradaki fark kaçırılan satış."
        )
    return metin


def _onset(column: str):
    """Riskin ilk goruldugu donemi doner.

    Bulunamazsa None -- son donemi uydurmak yerine "belirsiz" demek daha
    durust. Trend bazli riskler (birikim, sonumlenme) icin zaten tek bir
    baslangic donemi yoktur.
    """

    def resolve(row: RowMapping) -> str | None:
        value = row.get(column)
        return str(value) if value else None

    return resolve


def _stockout_impact(row: RowMapping) -> float | None:
    kayip_adet = _num(row, "ilk_cikis") - _num(row, "son_cikis")
    donem = _num(row, "sifir_stok_donem")
    fiyat = _num(row, "son_birim_satis")
    if kayip_adet <= 0 or donem <= 0:
        return None
    return kayip_adet * donem * fiyat


RISK_RULES = (
    RiskRule(
        code="STOCKOUT",
        title="Stok tükenmiş -- satış tedarikle sınırlı",
        severity=Severity.KRITIK,
        predicate=lambda _: (pl.col("son_stok") <= 0) & (pl.col("sifir_stok_donem") >= 2),
        narrative=_stockout_narrative,
        recommendation=(
            "Tedarik siparişini acil büyütün. Bu ürün kârlı ve talep var; kısıt "
            "tarafınızda. Tedarikçi teslim süresini ve minimum sipariş miktarını "
            "gözden geçirin."
        ),
        evidence_metrics=(
            "son_stok",
            "sifir_stok_donem",
            "arz_kisitli_donem",
            "son_marj_yuzde",
            "ilk_cikis",
            "son_cikis",
        ),
        impact=_stockout_impact,
        first_seen=lambda row: row.get("ilk_sifir_donem"),
    ),
    RiskRule(
        code="STOCKOUT_IMMINENT",
        title="Stok tükenmesine çok az kaldı",
        severity=Severity.YUKSEK,
        predicate=lambda _: (pl.col("son_stok") > 0)
        & (pl.col("son_kapama_ay").is_not_null())
        & (pl.col("son_kapama_ay") < KAPAMA_KRITIK_AY),
        narrative=lambda row: (
            f"Mevcut stok son 3 dönemin çıkış hızına göre yalnızca "
            f"{_num(row, 'son_kapama_ay'):.1f} ay yetiyor. Bu hızla devam ederse "
            "önümüzdeki dönem içinde tükenir."
        ),
        recommendation=(
            "Sipariş açın; tedarik süresi kapama süresinden uzunsa şimdiden geç "
            "kalınmış demektir."
        ),
        evidence_metrics=("son_stok", "son_kapama_ay", "son3_cikis_ort", "son_marj_yuzde"),
        impact=lambda row: _num(row, "son3_cikis_ort") * _num(row, "son_birim_satis"),
        first_seen=_onset("kritik_kapama_donem"),
    ),
    RiskRule(
        code="DEAD_STOCK",
        title="Ölü stok -- sermaye bağlı",
        severity=Severity.YUKSEK,
        predicate=lambda _: pl.col("son_kapama_ay") > KAPAMA_OLU_AY,
        narrative=lambda row: (
            f"Depoda {_num(row, 'son_stok'):.0f} adet var ve mevcut çıkış hızıyla "
            f"{_num(row, 'son_kapama_ay'):.1f} ay yetiyor. "
            f"{_tl(_num(row, 'son_stok_degeri_tl'))} sermaye bu üründe bağlı duruyor."
        ),
        recommendation=(
            "Yeni alımı durdurun. Kampanya, paket satış veya kanal değişikliğiyle "
            "stoğu eritmeyi değerlendirin."
        ),
        evidence_metrics=("son_stok", "son_kapama_ay", "son_stok_degeri_tl", "ortalama_cikis"),
        impact=lambda row: _num(row, "son_stok_degeri_tl"),
        first_seen=_onset("olu_stok_donem"),
    ),
    RiskRule(
        code="SLOW_MOVER",
        title="Yavaş hareket eden ürün",
        severity=Severity.ORTA,
        predicate=lambda _: (pl.col("son_kapama_ay") >= KAPAMA_YAVAS_AY)
        & (pl.col("son_kapama_ay") <= KAPAMA_OLU_AY),
        narrative=lambda row: (
            f"Stok kapama süresi {_num(row, 'son_kapama_ay'):.1f} ay. Kritik değil ama "
            f"{_tl(_num(row, 'son_stok_degeri_tl'))} sermaye ortalamanın üzerinde bir "
            "süre depoda bekliyor."
        ),
        recommendation="Sipariş miktarını küçültüp frekansı artırın; bağlı sermaye düşer.",
        evidence_metrics=("son_kapama_ay", "son_stok", "son_stok_degeri_tl"),
        impact=lambda row: _num(row, "son_stok_degeri_tl") * 0.5,
        first_seen=_onset("yavas_donem"),
    ),
    RiskRule(
        code="MARGIN_EROSION",
        title="Marj eriyor",
        severity=Severity.KRITIK,
        predicate=lambda _: pl.col("marj_degisim_puan") < -MARJ_EROZYON_PUAN,
        narrative=lambda row: (
            f"Brüt marj %{_num(row, 'ilk_marj_yuzde'):.1f} seviyesinden "
            f"%{_num(row, 'son_marj_yuzde'):.1f} seviyesine geriledi "
            f"({_num(row, 'marj_degisim_puan'):.1f} puan). Aynı dönemde birim maliyet "
            f"%{_num(row, 'maliyet_degisim_yuzde'):.1f} değişti; satış fiyatı bu artışı "
            "karşılamamış."
        ),
        recommendation=(
            "Satış fiyatını güncelleyin ya da tedarikçi ile fiyat görüşmesi açın. "
            "İkisi de mümkün değilse ürünün portföydeki yerini sorgulayın."
        ),
        evidence_metrics=(
            "ilk_marj_yuzde",
            "son_marj_yuzde",
            "marj_degisim_puan",
            "maliyet_degisim_yuzde",
            "son_birim_maliyet",
        ),
        impact=lambda row: abs(_num(row, "marj_degisim_puan"))
        / 100
        * _num(row, "son_cikis")
        * _num(row, "son_birim_satis"),
        first_seen=_onset("marj_dusus_donem"),
    ),
    RiskRule(
        code="COST_SHOCK",
        title="Birim maliyet kalıcı olarak yükseldi",
        severity=Severity.YUKSEK,
        predicate=lambda _: pl.col("maliyet_degisim_yuzde") > MALIYET_SOK_YUZDE,
        narrative=lambda row: (
            f"Birim maliyet dönem başından bu yana %{_num(row, 'maliyet_degisim_yuzde'):.1f} "
            f"arttı ve {_num(row, 'son_birim_maliyet'):.0f} TL seviyesine oturdu."
        ),
        recommendation=(
            "Fiyat listesini gözden geçirin; maliyet artışı kalıcı ise fiyata " "yansıtılmalı."
        ),
        evidence_metrics=("maliyet_degisim_yuzde", "son_birim_maliyet", "son_marj_yuzde"),
        impact=None,
        first_seen=_onset("maliyet_sok_donem"),
    ),
    RiskRule(
        code="SILENT_ACCUMULATION",
        title="Sessiz stok birikimi",
        severity=Severity.ORTA,
        predicate=lambda _: (pl.col("stok_trend_step") > 0)
        & (pl.col("net_akis_toplam") > 0)
        & (pl.col("cikis_trend_step") <= 0),
        narrative=lambda row: (
            f"Her dönem ortalama {_num(row, 'stok_trend_step'):.0f} adet stok birikiyor: "
            f"giriş çıkışı aşıyor ve talep artmıyor. Tek bir dönem alarma geçmiyor ama "
            f"trend {_num(row, 'ilk_stok'):.0f} adetten {_num(row, 'son_stok'):.0f} adete "
            "çıkmış durumda."
        ),
        recommendation="Sipariş miktarını çıkış hızına eşitleyin; aksi halde ölü stoğa dönüşür.",
        evidence_metrics=("stok_trend_step", "net_akis_toplam", "ilk_stok", "son_stok"),
        impact=lambda row: _num(row, "stok_trend_step")
        * _num(row, "periods_count")
        * _num(row, "son_birim_maliyet"),
        first_seen=None,
    ),
    RiskRule(
        code="DEMAND_SURGE",
        title="Talep hızlanıyor",
        severity=Severity.ORTA,
        predicate=lambda _: (pl.col("cikis_trend_step") > 0)
        & (pl.col("ilk3_cikis_ort") > 0)
        & (pl.col("son3_cikis_ort") > pl.col("ilk3_cikis_ort") * TALEP_PATLAMASI_KAT),
        narrative=lambda row: (
            f"Dönemsel çıkış ilk 3 ayda ortalama {_num(row, 'ilk3_cikis_ort'):.0f} adetken "
            f"son 3 ayda {_num(row, 'son3_cikis_ort'):.0f} adete çıktı. Bu bir fırsat, "
            "ama stok bu hıza hazır değilse tükenme riski de beraberinde geliyor."
        ),
        recommendation="Tedarik planını yukarı revize edin; büyüme trendini stoksuzluk kesmesin.",
        evidence_metrics=("ilk3_cikis_ort", "son3_cikis_ort", "son_stok", "son_kapama_ay"),
        impact=lambda row: (_num(row, "son3_cikis_ort") - _num(row, "ilk3_cikis_ort"))
        * _num(row, "son_birim_satis"),
        first_seen=_onset("talep_patlama_donem"),
    ),
    RiskRule(
        code="SEASONAL_PEAK",
        title="Mevsimsel tepe tespit edildi",
        severity=Severity.BILGI,
        predicate=lambda ctx: (pl.col("zirve_donem") != pl.col("first_period"))
        & (pl.col("zirve_donem") != pl.col("last_period"))
        & (pl.col("ortalama_cikis") > 0)
        & (pl.col("zirve_cikis") > pl.col("ortalama_cikis") * 1.2),
        narrative=lambda row: (
            f"Çıkış {row.get('zirve_donem')} döneminde {_num(row, 'zirve_cikis'):.0f} adetle "
            f"zirve yaptı; dönem ortalaması {_num(row, 'ortalama_cikis'):.0f} adet. "
            "Düz bir trend değil, mevsimsel bir hareket var."
        ),
        recommendation="Gelecek yıl aynı dönem için stoğu önceden planlayın.",
        evidence_metrics=("zirve_cikis", "ortalama_cikis", "son_stok"),
        impact=None,
        first_seen=lambda row: row.get("zirve_donem"),
    ),
    RiskRule(
        code="DYING_SKU",
        title="Sönümlenen ürün",
        severity=Severity.DUSUK,
        predicate=lambda _: (pl.col("cikis_trend_step") < 0)
        & (pl.col("ortalama_cikis") < 20)
        & (pl.col("son_stok") > 0),
        narrative=lambda row: (
            f"Dönemsel çıkış {_num(row, 'ilk_cikis'):.0f} adetten {_num(row, 'son_cikis'):.0f} "
            "adete geriledi ve hacim zaten düşük. Ürün portföyde yer kaplamaya devam ediyor."
        ),
        recommendation="Portföyden çıkarmayı ya da siparişi tamamen durdurmayı değerlendirin.",
        evidence_metrics=("ilk_cikis", "son_cikis", "ortalama_cikis", "son_stok"),
        impact=lambda row: _num(row, "son_stok_degeri_tl"),
        first_seen=None,
    ),
)


# ---------------------------------------------------------------------------
# AI prompt profili
# ---------------------------------------------------------------------------
PROMPT_PROFILE = PromptProfile(
    persona=(
        "Deri ve tekstil sektöründe 15 yıl çalışmış, üretim ve tedarik zinciri "
        "planlamasından sorumlu bir yönetim danışmanısın."
    ),
    domain_label="ERP stok ve satış raporu",
    entity_noun="urun",
    entity_noun_plural="urunler",
    departments=(
        Department("satinalma", "Satın Alma"),
        Department("uretim", "Üretim"),
        Department("satis", "Satış"),
        Department("finans", "Finans"),
    ),
    kpi_glossary={
        "kapama_ay": "Mevcut stoğun son 3 dönemin ortalama çıkış hızında kaç ay yeteceği.",
        "marj_yuzde": "Birim bazında brüt kâr yüzdesi: (satış - maliyet) / satış.",
        "arz_kisitli": "Stok sıfır ve çıkış girişe kilitli; satışı talep değil tedarik belirliyor.",
        "net_akis": "Giriş eksi çıkış. Sürekli pozitif olması stok birikimi demektir.",
        "stok_degeri_tl": "Dönem sonunda depoda bağlı olan sermaye (stok x birim maliyet).",
    },
    dynamics=(
        "mevsimsellik",
        "maliyet_artisi",
        "stok_riski",
        "talep_kaymasi",
        "marj_baskisi",
        "tedarik_kisiti",
    ),
    action_style=(
        "Aksiyonlar somut ve sahiplenilebilir olmalı: hangi departman, hangi ürün, "
        "hangi zaman ufku. 'Stokları optimize edin' gibi genel ifadeler kullanma."
    ),
)


PACK = DatasetPack(
    key="sonart-erp",
    title="Sonart Tekstil -- ERP Stok & Satış Raporu",
    description=(
        "Logo Netsis'ten alınan dönemsel stok hareket raporu. Ürün bazında giriş/çıkış, "
        "dönem sonu stok, birim maliyet ve satış fiyatı içerir."
    ),
    entity_key="stok_kodu",
    entity_label_key="urun_adi",
    period_key="donem",
    dimensions=("kategori", "depo"),
    columns=COLUMNS,
    derived_metrics=DERIVED_METRICS,
    integrity_rules=INTEGRITY_RULES,
    imputation_rules=IMPUTATION_RULES,
    risk_rules=RISK_RULES,
    period_aggregates=PERIOD_AGGREGATES,
    entity_aggregates=ENTITY_AGGREGATES,
    dimension_aggregates=DIMENSION_AGGREGATES,
    prompt_profile=PROMPT_PROFILE,
    entity_trend_column="cikis_miktar",
    snapshot_columns=(
        "donem_sonu_stok",
        "giris_miktar",
        "cikis_miktar",
        "marj_yuzde",
        "kapama_ay",
        "birim_maliyet_tl",
        "arz_kisitli",
    ),
    sample_file="sonart_erp_cok_donemli.csv",
)
