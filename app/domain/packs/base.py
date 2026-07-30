"""Dataset Pack sozlesmesi -- mimarinin merkez soyutlamasi.

Boru hattinin tamami (oku -> encoding onar -> sema dogrula -> kalite kontrol
-> zaman serisi -> risk -> AI) domain'den bagimsizdir. Bir rapor tipine ozgu
olan her sey burada tarif edilen tek bir *veri* nesnesinde toplanir.

Yeni bir rapor eklemek = yeni bir `DatasetPack` ornegi yazmak. Motora,
endpoint'lere veya AI katmanina dokunmak gerekmez. "300+ raporu tek
dashboard'a tasima" hedefinin kod tarafindaki karsiligi budur.

Neden Protocol degil de frozen dataclass?
    Pack bir *davranis* degil, *yapilandirma*. Python'da veri tasiyan bir
    soyutlama icin Protocol/ABC yazmak gereksiz toren olur. Protocol'u
    gercekten takas edilebilir davranis icin sakliyoruz: `LLMClient` ve
    `AnalysisCache` (bkz. app/ai/client.py, app/services/cache.py).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import polars as pl

from app.domain.models import ColumnType, IssueAction, MetricUnit, Severity

# ---------------------------------------------------------------------------
# Ifade insa baglami
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PackContext:
    """Polars ifadelerinin ihtiyac duydugu pack'e ozgu kolon adlari.

    Ifadeler dogrudan `pl.Expr` olarak degil, bu baglami alan bir fonksiyon
    olarak saklanir. Sebep: pencere fonksiyonlarinin `.over(entity_key)`
    demesi gerekiyor ve `entity_key` pack'ten pack'e degisiyor.
    """

    entity_key: str
    period_key: str
    entity_label_key: str


ExprBuilder = Callable[[PackContext], pl.Expr]
"""Baglami alip Polars ifadesi ureten fonksiyon."""

RowMapping = Mapping[str, Any]
"""Tek bir ozet satiri (entity_summary'den gelir)."""


# ---------------------------------------------------------------------------
# Sema
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ColumnDef:
    """Ham CSV kolonundan kanonik kolona esleme.

    `aliases` gercek ERP export'lari icin gerekli: ayni alan farkli
    sistemlerde farkli baslikla gelir (or. "cikis_miktar" / "Cikis Miktari").
    """

    canonical: str
    aliases: tuple[str, ...] = ()
    dtype: ColumnType = ColumnType.ONDALIK
    required: bool = True
    label: str = ""
    unit: MetricUnit = MetricUnit.SAYI

    def matches(self, header: str) -> bool:
        normalized = _normalize_header(header)
        candidates = {_normalize_header(self.canonical)} | {
            _normalize_header(a) for a in self.aliases
        }
        return normalized in candidates


def _normalize_header(value: str) -> str:
    """Baslik karsilastirmasi icin normalize: kucuk harf, bosluk/tire -> alt cizgi."""
    lowered = value.strip().lower()
    for turkish, ascii_ in (("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c")):
        lowered = lowered.replace(turkish, ascii_)
    for ch in (" ", "-", ".", "/"):
        lowered = lowered.replace(ch, "_")
    while "__" in lowered:
        lowered = lowered.replace("__", "_")
    return lowered.strip("_")


# ---------------------------------------------------------------------------
# Turetilmis metrikler
# ---------------------------------------------------------------------------
MetricStage = Literal["row", "window"]
"""row  : satir ici hesap, pencere gerektirmez (or. ciro = miktar * fiyat)
window : entity bazli pencere gerektirir (or. onceki doneme gore degisim)"""


@dataclass(frozen=True, slots=True)
class DerivedMetric:
    name: str
    label: str
    unit: MetricUnit
    build: ExprBuilder
    stage: MetricStage = "row"
    description: str = ""


# ---------------------------------------------------------------------------
# Veri butunlugu kurallari (kalite hatti)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class IntegrityRule:
    """Zenginlestirilmis tablo uzerinde calisan bir butunluk kontrolu.

    `violation` True donen satirlar ihlal sayilir.
    """

    code: str
    title: str
    severity: Severity
    action: IssueAction
    violation: ExprBuilder
    detail_template: str
    sample_columns: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Eksik deger tamamlama
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ImputationRule:
    """Eksik bir degeri veri setinin kendi ic tutarliligindan turetir.

    Ornek (Sonart): bir donemin `donem_sonu_stok` degeri bossa, stok
    mutabakatindan hesaplanabilir:
        onceki_donem_sonu + giris - cikis

    `backward` verilirse ayni deger bir de ters yonden (sonraki donemden geri)
    hesaplanir. Iki sonuc uyusmuyorsa deger yine de doldurulur ama
    "belirsiz imputasyon" uyarisi uretilir -- veri setinde gercek bir
    tutarsizlik oldugu anlamina gelir ve bunu sessizce gizlemek yanlis olur.
    """

    code: str
    title: str
    target_column: str
    forward: ExprBuilder
    detail: str
    backward: ExprBuilder | None = None
    tolerance: float = 0.5


# ---------------------------------------------------------------------------
# Is riski kurallari
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RiskRule:
    """Entity ozet tablosu uzerinde calisan is riski tespiti.

    `predicate`  : entity_summary uzerinde boolean ifade
    `narrative`  : eslesen satirdan Turkce aciklama uretir
    `impact`     : varsa parasal etki tahmini (TL)
    """

    code: str
    title: str
    severity: Severity
    predicate: ExprBuilder
    narrative: Callable[[RowMapping], str]
    recommendation: str
    evidence_metrics: tuple[str, ...]
    impact: Callable[[RowMapping], float | None] | None = None
    first_seen: Callable[[RowMapping], str | None] | None = None


# ---------------------------------------------------------------------------
# Toplulastirma tanimlari
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Aggregate:
    """Donem / entity / boyut ozetlerinde hesaplanacak bir alan."""

    name: str
    label: str
    unit: MetricUnit
    build: ExprBuilder
    headline: bool = False
    """True ise dashboard'un ust KPI kartlarinda gosterilir."""
    internal: bool = False
    """True ise yalnizca motorun ic mantigi icin hesaplanir ve AI baglamina
    konmaz. Ornek: bir riskin ilk goruldugu donemi bulan yardimci kolonlar --
    bu bilgi zaten risk sicilinde yer aldigi icin tabloda tekrar edilmesi
    sadece token harcar. Baglami kucuk tutmak dogrudan maliyet tasarrufu."""


# ---------------------------------------------------------------------------
# AI prompt profili
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Department:
    """Aksiyon sahibi departman.

    `key` sozlesme degeridir: modele verilen izinli liste ve API yanitindaki
    `owner` alani budur; ASCII ve degismez, cunku istemci buna gore dallanir.
    `label` yalnizca gosterim icindir. Ikisini ayirmak, ekranda "uretim"
    yazmasini ve etiketi degistirince istemcinin kirilmasini birlikte onler.
    """

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class PromptProfile:
    """Pack'e ozgu AI dili.

    Motor ayni, ama modelin konustugu dil rapora gore degisir: stok raporunda
    "satinalma / uretim", reklam raporunda "medya alimi / kreatif".
    """

    persona: str
    domain_label: str
    entity_noun: str
    entity_noun_plural: str
    departments: tuple[Department, ...]
    kpi_glossary: Mapping[str, str]
    dynamics: tuple[str, ...]
    action_style: str

    @property
    def department_keys(self) -> tuple[str, ...]:
        """Modele verilen izinli deger listesi."""
        return tuple(d.key for d in self.departments)

    def department_label(self, key: str) -> str:
        """Gosterim etiketi; taninmayan anahtar oldugu gibi geri doner."""
        for department in self.departments:
            if department.key == key:
                return department.label
        return key


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DatasetPack:
    """Bir rapor tipinin tam tanimi."""

    key: str
    title: str
    description: str

    entity_key: str
    entity_label_key: str
    period_key: str
    dimensions: tuple[str, ...]

    columns: tuple[ColumnDef, ...]
    derived_metrics: tuple[DerivedMetric, ...]
    integrity_rules: tuple[IntegrityRule, ...]
    imputation_rules: tuple[ImputationRule, ...]
    risk_rules: tuple[RiskRule, ...]

    period_aggregates: tuple[Aggregate, ...]
    entity_aggregates: tuple[Aggregate, ...]
    dimension_aggregates: tuple[Aggregate, ...]

    prompt_profile: PromptProfile

    entity_trend_column: str = ""
    """Entity ozetinde trend/mover hesaplarinin dayanacagi ana metrik."""

    snapshot_columns: tuple[str, ...] = ()
    """Bir donem analiz edilirken modele verilecek DONEM BAZLI kolonlar.

    Neden gerekli: entity ozet tablosu tum seriye ait toplamlar tasir
    (or. "sifir_stok_donem = 3"). Model tek bir donemi anlatirken donem
    bazli bir sayiya ihtiyac duyup elindeki tek degeri -- seri toplamini --
    odunc aliyor ve "3 donemdir stok sifir" gibi o doneme ait olmayan bir
    iddia kuruyor. Cozum modeli uyarmak degil, ihtiyaci olan sayiyi vermek:
    her donem sorusuna o donemin kayit bazli anlik goruntusu ekleniyor."""

    sample_file: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    # -- turetilmis yardimcilar ------------------------------------------
    @property
    def context(self) -> PackContext:
        return PackContext(
            entity_key=self.entity_key,
            period_key=self.period_key,
            entity_label_key=self.entity_label_key,
        )

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(c.canonical for c in self.columns if c.required)

    @property
    def numeric_columns(self) -> tuple[str, ...]:
        return tuple(
            c.canonical for c in self.columns if c.dtype in (ColumnType.TAMSAYI, ColumnType.ONDALIK)
        )

    @property
    def text_columns(self) -> tuple[str, ...]:
        return tuple(c.canonical for c in self.columns if c.dtype is ColumnType.METIN)

    @property
    def headline_aggregates(self) -> tuple[Aggregate, ...]:
        return tuple(a for a in self.period_aggregates if a.headline)

    def column(self, canonical: str) -> ColumnDef | None:
        return next((c for c in self.columns if c.canonical == canonical), None)

    def resolve_headers(self, headers: Sequence[str]) -> tuple[dict[str, str], list[str]]:
        """Ham basliklari kanonik adlara esler.

        Doner: (ham -> kanonik esleme, eksik zorunlu kolonlar)
        """
        mapping: dict[str, str] = {}
        for header in headers:
            for column in self.columns:
                if column.matches(header):
                    mapping[header] = column.canonical
                    break
        found = set(mapping.values())
        missing = [c for c in self.required_columns if c not in found]
        return mapping, missing
