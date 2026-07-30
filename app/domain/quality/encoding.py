"""Karakter kodlamasi tespiti ve mojibake onarimi.

Gercek bir Logo/Netsis export'unun en sik kusuru budur: dosya ya
Windows-1254 (Turkce) kodlanmistir, ya da UTF-8 iken bir yerde CP1252 gibi
okunup tekrar kaydedilmistir. Ikincisi "mojibake" uretir:

    Döşemelik   ->   DÃ¶ÅŸemelik
    Ayakkabılık ->   AyakkabÄ±lÄ±k
    Çantalık    ->   Ã‡antalÄ±k

Tasarim karari: kara kutu bir kutuphaneye guvenmek yerine *deterministik ve
aciklanabilir* bir karar zinciri kullaniyoruz. chardet yalnizca son care
tahmini olarak devreye giriyor. Sebep: mulakatta "neden bu kodlamayi sectin"
sorusuna "kutuphane oyle dedi" demek yerine kurali gosterebilmek.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Turkce'ye ozgu dogru karakterler -- onarim basarisini olcmek icin
_TURKISH_CHARS = frozenset("çğıöşüÇĞİÖŞÜâîû")

# Mojibake'nin imzasi: UTF-8'in cok baytli dizileri CP1252 olarak okundugunda
# neredeyse her zaman bu buyuk harflerle baslar.
_MOJIBAKE_LEAD = frozenset("ÃÄÅÎÏ")

# Turkce metinde mojibake'ye isaret eden karakteristik ciftler.
_MOJIBAKE_PAIRS = (
    "Ã¶",  # ö
    "Ã¼",  # ü
    "Ã§",  # ç
    "Ã‡",  # Ç
    "Ã–",  # Ö
    "Ãœ",  # Ü
    "Ä±",  # ı
    "Ä°",  # İ
    "ÄŸ",  # ğ
    "Äž",  # Ğ
    "ÅŸ",  # ş
    "Åž",  # Ş
)

_MOJIBAKE_RE = re.compile("|".join(re.escape(p) for p in _MOJIBAKE_PAIRS))

# Denenecek kodlamalar, oncelik sirasiyla.
#   utf-8-sig : BOM'lu UTF-8 (Excel'in "UTF-8 CSV" ciktisi)
#   cp1254    : Windows Turkce -- Logo/Netsis'in klasik ciktisi
#   iso8859-9 : Latin-5, cp1254'un standart karsiligi
_CANDIDATE_ENCODINGS = ("utf-8-sig", "utf-8", "cp1254", "iso8859-9", "cp1252")


@dataclass(frozen=True, slots=True)
class DecodeResult:
    text: str
    encoding: str
    repaired: bool
    repaired_samples: tuple[str, ...]
    suspect_unrepaired: bool
    """Mojibake izi var ama guvenli onarim yapilamadi -- veri bozulmasin diye
    dokunulmadi, sadece raporlandi."""


def _turkish_score(text: str) -> int:
    """Metindeki dogru Turkce karakter sayisindan mojibake izlerini duser."""
    correct = sum(1 for ch in text if ch in _TURKISH_CHARS)
    broken = len(_MOJIBAKE_RE.findall(text))
    lead = sum(1 for ch in text if ch in _MOJIBAKE_LEAD)
    return correct - (broken * 2) - lead


def looks_like_mojibake(text: str) -> bool:
    return bool(_MOJIBAKE_RE.search(text))


def repair_mojibake(text: str) -> str | None:
    """UTF-8'in CP1252 olarak okunmasindan dogan bozulmayi geri alir.

    Islem: metni CP1252 baytlarina geri cevir, sonra dogru sekilde UTF-8
    olarak coz.

    Guvenlik: bu round-trip *kendiliginden* korumalidir. Zaten dogru olan bir
    Turkce metin ("Döşemelik") 'ş' harfi CP1252'de bulunmadigi icin
    `.encode("cp1252")` asamasinda hata verir ve None doner -- yani saglam
    veriyi yanlislikla "onarma" riski yok.

    None doner: onarim guvenli degilse (kayipli mojibake, veya zaten dogru metin).
    """
    try:
        candidate = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if _turkish_score(candidate) <= _turkish_score(text):
        return None
    return candidate


def _sample_repairs(before: str, after: str, limit: int = 6) -> tuple[str, ...]:
    """Rapora koymak icin "onceki -> sonraki" ornekleri cikarir."""
    samples: list[str] = []
    seen: set[str] = set()
    for old_line, new_line in zip(before.splitlines(), after.splitlines(), strict=False):
        if old_line == new_line:
            continue
        for old_cell, new_cell in zip(old_line.split(","), new_line.split(","), strict=False):
            if old_cell == new_cell or not _MOJIBAKE_RE.search(old_cell):
                continue
            key = old_cell.strip()
            if key in seen:
                continue
            seen.add(key)
            samples.append(f"{old_cell.strip()} -> {new_cell.strip()}")
            if len(samples) >= limit:
                return tuple(samples)
    return tuple(samples)


def decode_bytes(raw: bytes) -> DecodeResult:
    """Ham baytlari metne cevirir; gerekiyorsa mojibake onarir.

    Karar zinciri:
      1. Aday kodlamalari sirayla dene, ilk basarili cozumu al.
      2. Cozulen metinde mojibake izi varsa guvenli onarimi dene.
      3. Onarim mumkun degilse veriyi degistirme, "suspect" olarak isaretle.
      4. Hicbir aday cozemezse chardet'e sor, o da olmazsa latin-1 (asla
         hata vermez) ile coz ve durumu raporla.
    """
    if not raw:
        return DecodeResult("", "utf-8", False, (), False)

    text: str | None = None
    used_encoding = ""

    for encoding in _CANDIDATE_ENCODINGS:
        try:
            decoded = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        text = decoded
        used_encoding = encoding
        break

    if text is None:
        text, used_encoding = _decode_with_fallback(raw)

    if not looks_like_mojibake(text):
        return DecodeResult(text, used_encoding, False, (), False)

    repaired = repair_mojibake(text)
    if repaired is None:
        # Kayipli bozulma: geri donusu olmayan bayt kaybi olmus. Veriyi
        # bozmaktansa oldugu gibi birakip raporluyoruz.
        return DecodeResult(text, used_encoding, False, (), True)

    return DecodeResult(
        text=repaired,
        encoding=f"{used_encoding} (mojibake onarıldı)",
        repaired=True,
        repaired_samples=_sample_repairs(text, repaired),
        suspect_unrepaired=False,
    )


def _decode_with_fallback(raw: bytes) -> tuple[str, str]:
    try:
        import chardet

        guess = chardet.detect(raw)
        encoding = guess.get("encoding")
        if encoding:
            return raw.decode(encoding, errors="replace"), f"{encoding} (chardet tahmini)"
    except Exception:
        pass
    return raw.decode("latin-1", errors="replace"), "latin-1 (son çare)"
