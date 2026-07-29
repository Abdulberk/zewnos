"""AI ciktisinin veriye dayandirilmasi ve sema zorlamasi."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.ai_schemas import Action, Evidence, PeriodAnalysis
from app.ai.context import build_shared_context, build_system_prompt
from app.ai.validation import FactIndex, collect_evidence, verify
from app.domain.models import AnalyticsResult
from app.domain.packs.base import DatasetPack


# ---------------------------------------------------------------------------
# Sema, kanitsiz aksiyonu reddeder
# ---------------------------------------------------------------------------
def test_kanitsiz_aksiyon_semadan_gecemez():
    """Mimarinin en kritik kurali sema seviyesinde kilitli."""
    with pytest.raises(ValidationError):
        Action(
            priority="kritik",
            title="Bir sey yapin",
            rationale="Cunku oyle",
            evidence=[],  # bos -> reddedilmeli
            owner="satinalma",
            horizon="bu_hafta",
        )


def test_kanitli_aksiyon_kabul_edilir():
    action = Action(
        priority="kritik",
        title="U005 siparisini buyutun",
        rationale="5 donemdir stok sifir",
        evidence=[Evidence(metric="son_stok", value=0.0, unit="adet", entity="U005")],
        owner="satinalma",
        horizon="bu_hafta",
    )
    assert action.evidence[0].entity == "U005"


def test_ic_ice_gecmis_yapidan_tum_kanitlar_toplanir():
    analysis = PeriodAnalysis(
        period="2026-03",
        headline="Test",
        delta_vs_prev="Onceki doneme gore maliyet artti",
        dominant_dynamics=["maliyet_artisi"],
        actions=[
            Action(
                priority="kritik",
                title="A",
                rationale="B",
                evidence=[
                    Evidence(metric="m1", value=1.0, unit="TL"),
                    Evidence(metric="m2", value=2.0, unit="TL"),
                ],
                owner="satis",
                horizon="bu_ay",
            )
        ],
        watch_items=[],
    )
    assert len(collect_evidence(analysis)) == 2


# ---------------------------------------------------------------------------
# FactIndex -- hesaplanmis her sayi bulunabilir olmali
# ---------------------------------------------------------------------------
def test_entity_ozetindeki_deger_bulunur(sonart_result: AnalyticsResult, sonart_pack: DatasetPack):
    index = FactIndex(sonart_result, sonart_pack)
    assert index.lookup("son_stok", "U004", None) == pytest.approx(4030.0)


def test_donem_ozetindeki_deger_bulunur(sonart_result: AnalyticsResult, sonart_pack: DatasetPack):
    index = FactIndex(sonart_result, sonart_pack)
    value = index.lookup("toplam_ciro_tl", None, "2026-06")
    assert value == pytest.approx(168696.0, abs=1)


def test_boyut_kiriliminda_kategori_degeri_bulunur(
    sonart_result: AnalyticsResult, sonart_pack: DatasetPack
):
    """Model 'Cantalik kategorisinin marji' gibi degerlere hakli olarak atif yapar.

    Boyut tablosu indekslenmezse gecerli bir kanit 'sapma' olarak raporlanir --
    yani dogrulayici, model dogru oldugu halde hata uretir.
    """
    index = FactIndex(sonart_result, sonart_pack)
    assert index.lookup("toplam_ciro_tl", "Çantalık", "2026-03") is not None


def test_turkce_karakter_farki_kaniti_gecersiz_kilmaz(
    sonart_result: AnalyticsResult, sonart_pack: DatasetPack
):
    """Model bazen 'Dosemelik' yazar, veride 'Döşemelik' vardir.

    Bu bir halusinasyon degil, yazim farki; normalize edilmeli.
    """
    index = FactIndex(sonart_result, sonart_pack)
    turkce = index.lookup("toplam_ciro_tl", "Döşemelik", "2026-03")
    ascii_ = index.lookup("toplam_ciro_tl", "Dosemelik", "2026-03")
    assert turkce is not None
    assert ascii_ == turkce


def test_olmayan_metrik_bulunamaz(sonart_result: AnalyticsResult, sonart_pack: DatasetPack):
    index = FactIndex(sonart_result, sonart_pack)
    assert index.lookup("uydurma_metrik", "U001", None) is None


# ---------------------------------------------------------------------------
# Dogrulama
# ---------------------------------------------------------------------------
def test_dogru_kanit_dogrulanir(sonart_result: AnalyticsResult, sonart_pack: DatasetPack):
    index = FactIndex(sonart_result, sonart_pack)
    report = verify([Evidence(metric="son_stok", value=4030.0, unit="adet", entity="U004")], index)
    assert report.verified == 1
    assert report.ratio == 1.0
    assert report.is_acceptable


def test_uydurulmus_deger_yakalanir(sonart_result: AnalyticsResult, sonart_pack: DatasetPack):
    index = FactIndex(sonart_result, sonart_pack)
    report = verify([Evidence(metric="son_stok", value=99999.0, unit="adet", entity="U004")], index)
    assert report.verified == 0
    issue = report.issues[0]
    assert issue.expected == pytest.approx(4030.0)
    assert "sap" in issue.reason.lower()


def test_uydurulmus_metrik_adi_yakalanir(sonart_result: AnalyticsResult, sonart_pack: DatasetPack):
    index = FactIndex(sonart_result, sonart_pack)
    report = verify([Evidence(metric="sihirli_oran", value=42.0, unit="oran")], index)
    assert report.verified == 0
    assert report.issues[0].expected is None


def test_yuvarlama_toleransi_hata_sayilmaz(
    sonart_result: AnalyticsResult, sonart_pack: DatasetPack
):
    """Model 4030 yerine 4030.4 yazarsa bu bir halusinasyon degil."""
    index = FactIndex(sonart_result, sonart_pack)
    report = verify([Evidence(metric="son_stok", value=4030.4, unit="adet", entity="U004")], index)
    assert report.verified == 1


def test_bos_kanit_listesi_kabul_edilebilir_sayilir(
    sonart_result: AnalyticsResult, sonart_pack: DatasetPack
):
    index = FactIndex(sonart_result, sonart_pack)
    report = verify([], index)
    assert report.ratio == 1.0
    assert report.is_acceptable


# ---------------------------------------------------------------------------
# Baglam insasi -- modele ham veri gitmemeli
# ---------------------------------------------------------------------------
def test_sistem_promptu_hesaplama_yasagini_icerir(sonart_pack: DatasetPack):
    prompt = build_system_prompt(sonart_pack)
    assert "Hicbir sayiyi kendin hesaplama" in prompt
    assert "kanit" in prompt.lower()
    # pack'e ozgu dil aktarilmis olmali
    assert "satinalma" in prompt


def test_paylasilan_baglam_tablolari_ve_risk_sicilini_icerir(
    sonart_result: AnalyticsResult, sonart_pack: DatasetPack, sonart_ingest
):
    context = build_shared_context(sonart_result, sonart_pack, sonart_ingest.report)
    assert "Donemsel portfoy ozeti" in context
    assert "Hesaplanmis risk sicili" in context
    assert "STOCKOUT" in context
    assert "Veri kalitesi notlari" in context
    # tum donemler tabloda olmali
    for period in sonart_result.periods:
        assert period in context


def test_ic_kolonlar_baglama_konmaz(sonart_result: AnalyticsResult, sonart_pack: DatasetPack):
    """Risk baslangic donemi yardimci kolonlari token harcamamali."""
    context = build_shared_context(sonart_result, sonart_pack)
    assert "kritik_kapama_donem" not in context
    assert "talep_patlama_donem" not in context


def test_donem_sorusu_yalnizca_o_donemi_hedefler(
    sonart_result: AnalyticsResult, sonart_pack: DatasetPack
):
    from app.ai.context import build_period_question

    delta = next(d for d in sonart_result.deltas if d.period == "2026-03")
    question = build_period_question("2026-03", delta, sonart_result, sonart_pack)
    assert "2026-03" in question
    assert "delta_vs_prev" in question
    # mover metrik adi teknik haliyle verilmeli ki model kanitta kopyalayabilsin
    assert "`cikis_miktar_change`" in question
