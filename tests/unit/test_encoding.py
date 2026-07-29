"""Karakter kodlamasi tespiti ve mojibake onarimi."""

from __future__ import annotations

import pytest

from app.domain.quality.encoding import (
    decode_bytes,
    looks_like_mojibake,
    repair_mojibake,
)
from tests.conftest import to_mojibake

TURKCE = "Marbella Döşemelik Deri,Ayakkabılık,Çantalık,Giyimlik"


def test_bozulmus_metin_tam_olarak_geri_kazanilir():
    bozuk = to_mojibake(TURKCE)
    assert bozuk != TURKCE
    assert looks_like_mojibake(bozuk)
    assert repair_mojibake(bozuk) == TURKCE


def test_saglam_turkce_metne_dokunulmaz():
    """En kritik guvenlik testi: onarim mekanizmasi dogru veriyi bozmamali.

    'ş' harfi CP1252'de bulunmadigi icin round-trip encode asamasinda hata
    verir ve onarim None doner -- yani mekanizma kendi kendini koruyor.
    """
    assert not looks_like_mojibake(TURKCE)
    assert repair_mojibake(TURKCE) is None


@pytest.mark.parametrize(
    ("bozuk", "beklenen"),
    [
        ("DÃ¶ÅŸemelik", "Döşemelik"),
        ("AyakkabÄ±lÄ±k", "Ayakkabılık"),
        ("Ã‡antalÄ±k", "Çantalık"),
        ("ÃœrÃ¼n", "Ürün"),
        ("GiriÅŸ", "Giriş"),
    ],
)
def test_bilinen_turkce_bozulma_ciftleri(bozuk: str, beklenen: str):
    assert repair_mojibake(bozuk) == beklenen


def test_utf8_dosya_oldugu_gibi_okunur():
    result = decode_bytes(TURKCE.encode("utf-8"))
    assert result.text == TURKCE
    assert result.repaired is False
    assert result.suspect_unrepaired is False


def test_mojibake_dosya_onarilir_ve_raporlanir():
    raw = to_mojibake(TURKCE).encode("utf-8")
    result = decode_bytes(raw)
    assert result.text == TURKCE
    assert result.repaired is True
    assert "mojibake onarildi" in result.encoding


def test_windows_1254_dosya_dogru_kodlamayla_okunur():
    """Logo/Netsis'in klasik ciktisi: Windows Turkce kodlamasi."""
    raw = TURKCE.encode("cp1254")
    result = decode_bytes(raw)
    assert result.text == TURKCE
    assert result.repaired is False


def test_bos_dosya_patlamadan_islenir():
    result = decode_bytes(b"")
    assert result.text == ""
    assert result.repaired is False


def test_gecersiz_baytlar_son_care_ile_okunur():
    """Hicbir aday kodlama cozemezse veri kaybedilmez, uyari verilir."""
    result = decode_bytes(b"\xff\xfe\x00kod,ad\n1,test\n")
    assert result.text  # bos donmemeli
    assert result.encoding
