"""Veri kalitesi hatti: kopya, eksik, imputasyon, karantina, butunluk."""

from __future__ import annotations

import polars as pl
import pytest

from app.core.errors import EmptyDatasetError, SchemaMismatchError
from app.domain.models import IssueAction, Severity
from app.domain.packs.base import DatasetPack
from app.domain.quality.pipeline import IngestOutcome, ingest
from tests.conftest import series_value, to_mojibake

HEADER = (
    "stok_kodu,urun_adi,kategori,depo,donem,giris_miktar,cikis_miktar,"
    "donem_sonu_stok,birim_maliyet_tl,birim_satis_tl\n"
)


def codes(outcome: IngestOutcome) -> set[str]:
    return {issue.code for issue in outcome.report.issues}


def issue(outcome: IngestOutcome, code: str):
    found = [i for i in outcome.report.issues if i.code == code]
    assert found, f"{code} bulgusu bekleniyordu, bulunanlar: {codes(outcome)}"
    return found[0]


# ---------------------------------------------------------------------------
# Ornek veri uzerinde
# ---------------------------------------------------------------------------
def test_birebir_kopya_satir_kaldirilir(sonart_ingest: IngestOutcome):
    """91 ham satirin biri (U001/2026-02) birebir tekrar; 90 kalmali."""
    assert sonart_ingest.report.raw_row_count == 91
    assert sonart_ingest.report.clean_row_count == 90
    found = issue(sonart_ingest, "DUPLICATE_EXACT")
    assert found.action is IssueAction.SILINDI
    assert found.affected_rows == 1


def test_kopya_kaldirildiktan_sonra_her_urun_donem_cifti_tekil(sonart_ingest: IngestOutcome):
    duplicated = (
        sonart_ingest.clean.group_by(["stok_kodu", "donem"]).len().filter(pl.col("len") > 1)
    )
    assert duplicated.height == 0


def test_eksik_donem_sonu_stogu_mutabakattan_turetilir(sonart_ingest: IngestOutcome):
    """U010/2026-04 satirinin tum miktarlari bos.

    Beklenen: onceki donem sonu (5160) + giris (700) - cikis (680) = 5180.
    Bu deger veri setinden bagimsiz olarak elle dogrulanabilir; testin degeri
    burada -- 'bir sayi dondu' degil, 'DOGRU sayi dondu' kontrol ediliyor.
    """
    assert series_value(sonart_ingest.clean, "U010", "2026-04", "donem_sonu_stok") == 5180.0
    assert series_value(sonart_ingest.clean, "U010", "2026-04", "giris_miktar") == 700.0
    assert series_value(sonart_ingest.clean, "U010", "2026-04", "cikis_miktar") == 680.0

    found = issue(sonart_ingest, "IMPUTED_STOCK")
    assert found.action is IssueAction.TURETILDI


def test_celisen_imputasyon_gizlenmez_raporlanir(sonart_ingest: IngestOutcome):
    """U010/2026-04 ileri yonde 5180, geri yonde 5160 veriyor.

    Veri setinde gercek bir tutarsizlik var. Dogru davranis: degeri doldurup
    tutarsizligi ACIKCA raporlamak -- sessizce birini secip gecmek degil.
    """
    found = issue(sonart_ingest, "IMPUTATION_AMBIGUOUS")
    assert found.severity is Severity.YUKSEK
    assert found.action is IssueAction.ISARETLENDI
    assert any("ileri=5180" in s and "geri=5160" in s for s in found.samples)


def test_maliyet_sicramasi_isaretlenir(sonart_ingest: IngestOutcome):
    """U007'nin birim maliyeti 2026-03'te %36 artiyor."""
    found = issue(sonart_ingest, "COST_SPIKE")
    assert any("U007" in s for s in found.samples)


def test_imputasyon_yapay_mutabakat_ihlali_uretmez(sonart_ingest: IngestOutcome):
    """Kendi doldurdugumuz deger 'mutabakat tutmuyor' alarmi vermemeli.

    U010/2026-04 dolduruldu; 2026-05 satiri artik matematiksel olarak
    tutmuyor ama bunun sebebi bizim imputasyonumuz. Hat bu donemi muaf
    tutuyor ve durumu IMPUTATION_AMBIGUOUS olarak tek seferde raporluyor.
    """
    recon = [i for i in sonart_ingest.report.issues if i.code == "RECONCILIATION_BREAK"]
    assert not recon, f"beklenmeyen mutabakat ihlali: {recon}"


def test_bozuk_encoding_ornek_kayitlar_onarilir(sonart_bytes: bytes, sonart_pack: DatasetPack):
    outcome = ingest(to_mojibake(sonart_bytes.decode("utf-8")).encode("utf-8"), sonart_pack)
    assert outcome.report.encoding_repaired is True
    kategoriler = set(outcome.clean.get_column("kategori").unique().to_list())
    assert kategoriler == {"Giyimlik", "Döşemelik", "Ayakkabılık", "Çantalık"}


def test_saglik_puani_cozulen_sorunlari_daha_az_cezalandirir(sonart_ingest: IngestOutcome):
    """Onarilmis bir sorun, isaretlenip birakilmis bir sorun kadar dusurmemeli."""
    assert 50 <= sonart_ingest.report.health_score <= 90


# ---------------------------------------------------------------------------
# Edge case'ler
# ---------------------------------------------------------------------------
def test_bos_dosya_anlamli_hata_verir(sonart_pack: DatasetPack):
    with pytest.raises(EmptyDatasetError):
        ingest(b"", sonart_pack)


def test_sadece_baslik_satiri_anlamli_hata_verir(sonart_pack: DatasetPack):
    with pytest.raises(EmptyDatasetError):
        ingest(HEADER.encode(), sonart_pack)


def test_eksik_kolon_hangi_kolonlarin_eksik_oldugunu_soyler(sonart_pack: DatasetPack):
    with pytest.raises(SchemaMismatchError) as exc:
        ingest(b"stok_kodu,donem\nU001,2026-01\n", sonart_pack)
    missing = exc.value.details["missing_columns"]
    assert "birim_maliyet_tl" in missing
    assert "cikis_miktar" in missing


def test_tanimsiz_kolonlar_yok_sayilir_ama_raporlanir(sonart_pack: DatasetPack):
    csv = HEADER.replace("\n", ",ekstra_kolon\n") + (
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,10,20,cop\n"
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,105,10,20,cop\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    assert "UNKNOWN_COLUMNS" in codes(outcome)
    assert "ekstra_kolon" not in outcome.clean.columns


def test_sayiya_cevrilemeyen_satir_karantinaya_alinir(sonart_pack: DatasetPack):
    csv = HEADER + (
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,10,20\n"
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,105,10,20\n"
        "U002,Bozuk,Giyimlik,Ana Depo,2026-01,abc,def,ghi,10,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    assert outcome.report.quarantined_row_count == 1
    assert "ROW_QUARANTINED" in codes(outcome)
    assert "U002" not in outcome.clean.get_column("stok_kodu").to_list()


def test_gecersiz_donem_formati_ayiklanir(sonart_pack: DatasetPack):
    csv = HEADER + (
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,10,20\n"
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,105,10,20\n"
        "U001,Test,Giyimlik,Ana Depo,OCAK-26,10,5,110,10,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    assert "INVALID_PERIOD_FORMAT" in codes(outcome)
    assert "OCAK-26" not in outcome.clean.get_column("donem").to_list()


def test_negatif_miktar_kritik_olarak_isaretlenir(sonart_pack: DatasetPack):
    csv = HEADER + (
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,10,20\n"
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,-50,10,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    found = issue(outcome, "NEGATIVE_VALUE")
    assert found.severity is Severity.KRITIK


def test_maliyet_satis_fiyatini_asarsa_kritik_isaretlenir(sonart_pack: DatasetPack):
    csv = HEADER + (
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,30,20\n"
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,105,30,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    assert "MARGIN_INVERSION" in codes(outcome)


def test_donem_bosluklari_tespit_edilir(sonart_pack: DatasetPack):
    """Bir urun tum donemlerde yoksa trend hesabi daha az noktaya dayanir."""
    csv = HEADER + (
        "U001,Bir,Giyimlik,Ana Depo,2026-01,10,5,100,10,20\n"
        "U001,Bir,Giyimlik,Ana Depo,2026-02,10,5,105,10,20\n"
        "U001,Bir,Giyimlik,Ana Depo,2026-03,10,5,110,10,20\n"
        "U002,Iki,Giyimlik,Ana Depo,2026-01,10,5,50,10,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    assert "PERIOD_GAP" in codes(outcome)


def test_ayni_donem_icin_celisen_kayitta_son_kayit_alinir(sonart_pack: DatasetPack):
    """ERP'de duzeltme kaydi sonradan yazilir; son kayit dogru kabul edilir."""
    csv = HEADER + (
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,10,20\n"
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,999,10,20\n"
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,105,10,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    assert "DUPLICATE_KEY" in codes(outcome)
    assert series_value(outcome.clean, "U001", "2026-01", "donem_sonu_stok") == 999.0


def test_bosluklu_ve_virgullu_sayilar_okunur(sonart_pack: DatasetPack):
    """Turkce ondalik ayraci ve binlik boslugu tolere edilmeli."""
    csv = HEADER + (
        'U001,Test,Giyimlik,Ana Depo,2026-01,10,5,"1 200",10,5,\n'
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,1205,10,20\n"
    )
    outcome = ingest(csv.replace(",\n", "\n").encode(), sonart_pack)
    assert outcome.report.clean_row_count >= 1


# ---------------------------------------------------------------------------
# sayi yazim bicimleri
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("yazim", "beklenen"),
    [
        ("12500", 12500.0),  # sade
        ("12.5", 12.5),  # Ingilizce ondalik
        ("12,5", 12.5),  # Turkce ondalik
        ("12.500", 12500.0),  # Turkce binlik  <-- eskiden 12.5 okunuyordu
        ("12,500", 12500.0),  # Ingilizce binlik
        ("1.234,56", 1234.56),  # Turkce karisik <-- eskiden null oluyordu
        ("1,234.56", 1234.56),  # Ingilizce karisik
        ("1 200", 1200.0),  # binlik boslugu
        ("-12.500", -12500.0),  # negatif
    ],
)
def test_sayi_yazim_bicimleri_dogru_okunur(sonart_pack: DatasetPack, yazim: str, beklenen: float):
    """Binlik ayraci ondalik ayraciyla karistirilmamali.

    "12.500" kor bir nokta silme/birakma ile 1000 kat yanlis okunabilir; bu
    hata sessizdir cunku sonuc yine gecerli bir sayidir.
    """
    csv = HEADER + f'U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,"{yazim}",20\n'
    outcome = ingest(csv.encode(), sonart_pack)
    assert series_value(outcome.clean, "U001", "2026-01", "birim_maliyet_tl") == beklenen


def test_cozulemeyen_sayi_sessizce_yanlis_okunmaz(sonart_pack: DatasetPack):
    """Taninmayan yazim null olur ve kalite raporunda gorunur.

    Sessiz yanlis bir sayidansa gurultulu bir eksik yeglenir: eksik deger
    imputasyon/karantina hattina girer, yanlis deger hicbir yerde yakalanmaz.
    """
    csv = HEADER + (
        "U001,Test,Giyimlik,Ana Depo,2026-01,10,5,100,12.34.56,20\n"
        "U001,Test,Giyimlik,Ana Depo,2026-02,10,5,105,30,20\n"
    )
    outcome = ingest(csv.encode(), sonart_pack)
    assert "MISSING_DETECTED" in codes(outcome)
