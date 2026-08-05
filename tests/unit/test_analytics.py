"""Zaman serisi motoru: pencere guvenligi, turetilmis metrikler, riskler."""

from __future__ import annotations

import polars as pl
import pytest

from app.domain.analytics.engine import analyze
from app.domain.analytics.series import build_series
from app.domain.models import AnalyticsResult, Severity
from app.domain.packs.base import DatasetPack
from app.domain.quality.pipeline import IngestOutcome, ingest
from tests.conftest import entity_row, risk_codes, series_value

HEADER = (
    "stok_kodu,urun_adi,kategori,depo,donem,giris_miktar,cikis_miktar,"
    "donem_sonu_stok,birim_maliyet_tl,birim_satis_tl\n"
)


# ---------------------------------------------------------------------------
# Pencere guvenligi -- zaman serisi analizinin 1 numarali hatasi
# ---------------------------------------------------------------------------
def test_pencere_hesaplari_urun_sinirini_asmaz(
    sonart_ingest: IngestOutcome, sonart_pack: DatasetPack
):
    """Bir urunun son donemi bir sonraki urunun ilk donemine sizmamali.

    `.over(entity_key)` olmadan `shift(1)` tam olarak bunu yapar ve hata
    sessizdir: sonuc uretilir ama yanlistir. Her urunun ILK doneminde
    `onceki_stok` null olmali.
    """
    series = build_series(sonart_ingest.clean, sonart_pack)
    first_periods = series.group_by("stok_kodu").agg(
        pl.col("onceki_stok").sort_by("donem").first().alias("ilk_onceki")
    )
    assert first_periods.get_column("ilk_onceki").null_count() == first_periods.height


def test_iki_urun_arasinda_kasitli_sizma_kurulursa_yakalanir(sonart_pack: DatasetPack):
    """Kontrol testi: U001'in son stogu U002'nin ilk 'onceki_stok'u olmamali."""
    csv = HEADER + (
        "U001,Bir,Giyimlik,Ana Depo,2026-01,0,0,100,10,20\n"
        "U001,Bir,Giyimlik,Ana Depo,2026-02,0,0,100,10,20\n"
        "U002,Iki,Giyimlik,Ana Depo,2026-01,0,0,555,10,20\n"
        "U002,Iki,Giyimlik,Ana Depo,2026-02,0,0,555,10,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    series = build_series(outcome.clean, sonart_pack)
    u002_first = series.filter((pl.col("stok_kodu") == "U002") & (pl.col("donem") == "2026-01"))
    assert u002_first.get_column("onceki_stok").item() is None


# ---------------------------------------------------------------------------
# Turetilmis metrikler
# ---------------------------------------------------------------------------
def test_marj_yuzdesi_dogru_hesaplanir(sonart_ingest: IngestOutcome, sonart_pack: DatasetPack):
    """U007/2026-01: (210 - 120) / 210 = %42.857"""
    series = build_series(sonart_ingest.clean, sonart_pack)
    value = series_value(series, "U007", "2026-01", "marj_yuzde")
    assert value == pytest.approx(42.857, abs=0.01)


def test_kapama_ayi_son_uc_donem_ortalamasina_gore_hesaplanir(
    sonart_ingest: IngestOutcome, sonart_pack: DatasetPack
):
    """U004/2026-06: stok 4030, son 3 donem ort. cikis 295 -> 13.66 ay."""
    series = build_series(sonart_ingest.clean, sonart_pack)
    assert series_value(series, "U004", "2026-06", "kapama_ay") == pytest.approx(13.66, abs=0.05)


def test_arz_kisitli_bayragi_dogru_kosulda_yanar(
    sonart_ingest: IngestOutcome, sonart_pack: DatasetPack
):
    """U005/2026-03: stok 0 ve cikis (77) girise (77) kilitli."""
    series = build_series(sonart_ingest.clean, sonart_pack)
    assert series_value(series, "U005", "2026-03", "arz_kisitli") == 1
    # U005/2026-01: stok 2, cikis 170 > giris 77 -> kisitli degil
    assert series_value(series, "U005", "2026-01", "arz_kisitli") == 0


def test_mutabakat_tek_bilinen_tutarsizlik_disinda_tutar(
    sonart_ingest: IngestOutcome, sonart_pack: DatasetPack
):
    """Yanlis alarm kontrolu + bilinen tutarsizligin sabitlenmesi.

    Ornek veride mutabakati bozan TEK bir yer var: U010/2026-05. Sebebi
    U010/2026-04 satirinin bos olmasi ve komsu donemlerin birbiriyle
    celismesi -- ileri yonde 5180, geri yonde 5160 cikiyor (bkz.
    test_celisen_imputasyon_gizlenmez_raporlanir). Ileri yondeki degeri
    kullandigimiz icin Mayis satiri 20 adet acik veriyor.

    Bu testin degeri: (1) diger 74 satirda yanlis alarm uretmedigimizi,
    (2) bu tek sapmanin bilinen ve belgelenmis oldugunu kanitlamak.
    Hatta gozardi etmek yerine miktarini teste yazmak dogru olan.
    """
    series = build_series(sonart_ingest.clean, sonart_pack)
    checkable = series.filter(pl.col("onceki_stok").is_not_null())

    offenders = checkable.filter(pl.col("mutabakat_farki").abs() > 0.5).select(
        ["stok_kodu", "donem", "mutabakat_farki"]
    )
    assert offenders.height == 1, f"beklenmeyen mutabakat ihlalleri: {offenders.to_dicts()}"

    row = offenders.to_dicts()[0]
    assert (row["stok_kodu"], row["donem"]) == ("U010", "2026-05")
    assert row["mutabakat_farki"] == pytest.approx(-20.0, abs=0.01)

    # geri kalan her satir kurusu kurusuna tutmali
    clean_rows = checkable.filter(pl.col("mutabakat_farki").abs() <= 0.5)
    assert clean_rows.height == checkable.height - 1
    assert clean_rows.height > 70


# ---------------------------------------------------------------------------
# Risk kurallari -- her biri veriden dogrulanabilir
# ---------------------------------------------------------------------------
def test_u005_stok_tukenmesi_olarak_isaretlenir(sonart_result: AnalyticsResult):
    """Stok Subat'tan beri 0, cikis girise kilitli. Tukenme 2026-02'de basliyor."""
    assert "STOCKOUT" in risk_codes(sonart_result, "U005")
    risk = next(r for r in sonart_result.risks if r.entity == "U005" and r.code == "STOCKOUT")
    assert risk.severity is Severity.KRITIK
    assert risk.first_seen_period == "2026-02"
    assert risk.financial_impact_tl == pytest.approx(33480.0, abs=1)


def test_u003_tukenmesi_nisanda_baslar(sonart_result: AnalyticsResult):
    """Stok 110 -> 70 -> 30 -> 0. Ilk sifir donemi Nisan, Mart degil."""
    risk = next(r for r in sonart_result.risks if r.entity == "U003" and r.code == "STOCKOUT")
    assert risk.first_seen_period == "2026-04"


def test_u004_olu_stok_olarak_isaretlenir(sonart_result: AnalyticsResult):
    """13.66 ay kapama; 4030 x 9 TL = 36.270 TL bagli sermaye."""
    risk = next(r for r in sonart_result.risks if r.entity == "U004" and r.code == "DEAD_STOCK")
    assert risk.financial_impact_tl == pytest.approx(36270.0, abs=1)


def test_u007_marj_erozyonu_ve_maliyet_soku(sonart_result: AnalyticsResult):
    """Marj %42.86 -> %30.48; birim maliyet 120 -> 146. Kirilma Mart'ta."""
    codes = risk_codes(sonart_result, "U007")
    assert {"MARGIN_EROSION", "COST_SHOCK", "STOCKOUT_IMMINENT"} <= codes
    erosion = next(
        r for r in sonart_result.risks if r.entity == "U007" and r.code == "MARGIN_EROSION"
    )
    assert erosion.first_seen_period == "2026-03"
    row = entity_row(sonart_result, "U007")
    assert row["marj_degisim_puan"] == pytest.approx(-12.38, abs=0.05)


def test_u002_sessiz_birikim_yakalanir(sonart_result: AnalyticsResult):
    """Hicbir tek donem alarm vermez: giris 600 > cikis 560, stok 740 -> 940.

    Bu risk tanim geregi yalnizca zaman serisinden gorulebilir.
    """
    assert "SILENT_ACCUMULATION" in risk_codes(sonart_result, "U002")
    row = entity_row(sonart_result, "U002")
    assert row["stok_trend_step"] == pytest.approx(40.0, abs=0.1)


def test_u011_talep_hizlanmasi_yakalanir(sonart_result: AnalyticsResult):
    """Cikis 22 -> 117; ilk 3 ort. 28.3, son 3 ort. 81."""
    assert "DEMAND_SURGE" in risk_codes(sonart_result, "U011")
    row = entity_row(sonart_result, "U011")
    assert row["ilk3_cikis_ort"] == pytest.approx(28.33, abs=0.1)
    assert row["son3_cikis_ort"] == pytest.approx(81.0, abs=0.1)


def test_u006_mevsimsel_tepe_nisanda(sonart_result: AnalyticsResult):
    """Cikis 195/218/310/356/322/241 -> zirve Nisan, seri ucunda degil."""
    risk = next(r for r in sonart_result.risks if r.entity == "U006" and r.code == "SEASONAL_PEAK")
    assert risk.first_seen_period == "2026-04"


def test_u014_sonumlenen_urun(sonart_result: AnalyticsResult):
    assert "DYING_SKU" in risk_codes(sonart_result, "U014")


def test_saglikli_urun_yanlis_alarm_almaz(sonart_result: AnalyticsResult):
    """U015 istikrarli: sabit cikis, sabit marj, makul stok.

    Yanlis pozitif kontrolu -- her urune risk yazan bir motor ise yaramaz.
    """
    assert not risk_codes(sonart_result, "U015") - {"SEASONAL_PEAK"}


# ---------------------------------------------------------------------------
# Donemsel farklilasma
# ---------------------------------------------------------------------------
def test_her_donemde_farkli_riskler_acilir(sonart_result: AnalyticsResult):
    """Puan tablosundaki 'donemsel farklilasma' kaleminin veri tarafi.

    Riskler tek bir doneme yigilmamali; her donemin kendi hikayesi olmali.
    """
    by_period = {d.period: set(d.new_risks) for d in sonart_result.deltas}
    assert "STOCKOUT" in by_period["2026-02"]
    assert {"COST_SHOCK", "MARGIN_EROSION"} <= by_period["2026-03"]
    assert "DEMAND_SURGE" in by_period["2026-04"]
    # en az 4 farkli donemde yeni risk acilmis olmali
    assert sum(1 for risks in by_period.values() if risks) >= 4


def test_donem_deltalari_onceki_donemi_dogru_referanslar(sonart_result: AnalyticsResult):
    assert sonart_result.deltas[0].previous_period is None
    for previous, current in zip(sonart_result.deltas, sonart_result.deltas[1:], strict=False):
        assert current.previous_period == previous.period


def test_en_cok_degisen_kayitlar_hesaplanir(sonart_result: AnalyticsResult):
    """2026-03'te U006'nin cikisi 218 -> 310 (+92) ile en cok artan."""
    delta = next(d for d in sonart_result.deltas if d.period == "2026-03")
    top = delta.movers_up[0]
    assert top.entity == "U006"
    assert top.value == pytest.approx(92.0, abs=0.1)


# ---------------------------------------------------------------------------
# Reklam pack'i -- ayni motor, farkli rapor
# ---------------------------------------------------------------------------
def test_ads_kitle_yorulmasi_yakalanir(ads_result: AnalyticsResult):
    """K011: frekans 1.6 -> 4.3, CTR duser, ROAS 1.17 -> 0.33."""
    codes = {r.code for r in ads_result.risks if r.entity == "K011"}
    assert "AD_FATIGUE" in codes
    row = entity_row(ads_result, "K011", key="kampanya_id")
    assert row["frekans_degisim"] == pytest.approx(2.7, abs=0.05)
    assert row["son_roas"] == pytest.approx(0.3276, abs=0.001)


def test_ads_verimsiz_olcekleme_yakalanir(ads_result: AnalyticsResult):
    """K006: harcama 3120 -> 9360 (%200), ROAS 0.80 -> 0.49."""
    codes = {r.code for r in ads_result.risks if r.entity == "K006"}
    assert {"SCALING_INEFFICIENCY", "UNPROFITABLE"} <= codes
    row = entity_row(ads_result, "K006", key="kampanya_id")
    assert row["harcama_degisim_yuzde"] == pytest.approx(200.0, abs=0.5)


def test_ads_yildiz_kampanya_olceklemeye_isaretlenir(ads_result: AnalyticsResult):
    """K005: ROAS sabit 5.0, frekans 1.5 -- kitle doymamis."""
    codes = {r.code for r in ads_result.risks if r.entity == "K005"}
    assert "STAR_SCALE_UP" in codes
    row = entity_row(ads_result, "K005", key="kampanya_id")
    assert row["son_roas"] == pytest.approx(5.0, abs=0.01)


def test_ads_verimli_buyume_yorulmadan_ayrilir(ads_result: AnalyticsResult):
    """K001: harcama 4.25x artmis ama ROAS 3.28'de sabit -- bu yorulma degil.

    Motorun 'her harcama artisi kotudur' demedigini kanitlar.
    """
    codes = {r.code for r in ads_result.risks if r.entity == "K001"}
    assert "EFFICIENT_GROWTH" in codes
    assert "AD_FATIGUE" not in codes
    assert "SCALING_INEFFICIENCY" not in codes


# ---------------------------------------------------------------------------
# Jeneriklik
# ---------------------------------------------------------------------------
def test_ayni_motor_iki_pack_ile_calisir(
    sonart_result: AnalyticsResult, ads_result: AnalyticsResult
):
    for result in (sonart_result, ads_result):
        assert len(result.periods) == 6
        assert result.entity_count == 15
        assert result.risks
        assert result.headline_metrics
        assert len(result.deltas) == 6


def test_tek_donemli_veri_patlamaz(sonart_pack: DatasetPack):
    """Trend hesaplari en az iki noktaya ihtiyac duyar; tek donem cokmemeli."""
    csv = HEADER + "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,10,20\n"
    outcome = ingest(csv.encode(), sonart_pack)
    result = analyze(outcome.clean, sonart_pack)
    assert result.periods == ("2026-01",)
    assert result.deltas[0].previous_period is None
    assert entity_row(result, "U001")["trend_step"] == 0.0


def test_departman_anahtari_ile_etiketi_ayridir(sonart_pack, ads_pack):
    """Sozlesme degeri ASCII kalir, ekranda gorunen etiket Turkce olur.

    Ikisi ayni alan olsaydi ya API'de "Üretim" doner (istemci dallanmasi
    kirilgan olur) ya da PDF'te "uretim" yazardi.
    """
    for pack in (sonart_pack, ads_pack):
        profile = pack.prompt_profile
        for key in profile.department_keys:
            assert key.isascii(), f"{pack.key}: sozlesme degeri ASCII olmali -> {key}"
            assert key == key.lower()
            assert profile.department_label(key) != "", f"{pack.key}: {key} etiketsiz"

    sonart = sonart_pack.prompt_profile
    assert sonart.department_label("uretim") == "Üretim"
    # taninmayan anahtar sessizce kaybolmaz, oldugu gibi doner
    assert sonart.department_label("bilinmeyen") == "bilinmeyen"


def test_cors_kokenleri_ortamdan_okunur(monkeypatch):
    """Dagitilmis arayuzun adresi kodda degil ayarda olmali.

    pydantic-settings list[str] alanini ortamdan yalnizca JSON olarak cozer ve
    bunu alan dogrulayicisindan once yapar; bu yuzden alan duz metin tutulup
    `allowed_origins` ile listeye ceviriliyor. Dagitim panellerine JSON yazmak
    hataya acik oldugu icin virgullu biçim destekleniyor.
    """
    from app.core.config import Settings

    varsayilan = Settings(_env_file=None)
    assert varsayilan.allowed_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    monkeypatch.setenv("CORS_ORIGINS", "https://a.vercel.app, https://b.example.com")
    assert Settings(_env_file=None).allowed_origins == [
        "https://a.vercel.app",
        "https://b.example.com",
    ]
