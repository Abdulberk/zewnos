"""AI cikti sozlesmesi.

Bu semalar modele *zorlanir* (Anthropic structured outputs). Mimarinin en
kritik kurali burada kodlanmistir:

    Sayiyi Polars hesaplar, AI yorumlar.

Her aksiyon en az bir `Evidence` tasimak zorunda ve her Evidence, motorun
urettigi tablolarda gercekten bulunan bir metrige isaret etmeli. Sema
seviyesinde zorunlu tutuldugu icin "kanitsiz aksiyon" ciktidan gecemez;
ustune servis katmani her kaniti hesaplanmis degerle karsilastirir
(bkz. app/ai/validation.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["kritik", "yuksek", "orta", "dusuk"]
Horizon = Literal["bu_hafta", "bu_ay", "bu_ceyrek"]
Confidence = Literal["yuksek", "orta", "dusuk"]


class Evidence(BaseModel):
    """Bir iddianin dayandigi somut sayi."""

    metric: str = Field(description="Metrigin teknik adi, or. 'son_kapama_ay'.")
    value: float = Field(description="Verilen tablolardaki degerin aynisi.")
    unit: str = Field(description="Birim: TL, adet, %, ay, oran, sayi.")
    entity: str | None = Field(
        default=None,
        description=(
            "Degerin ait oldugu kapsam. Tek bir kayit ise kodu ('U005', 'K011'); "
            "bir kategori/depo/platform kirilimi ise o boyutun adi ('Cantalik', "
            "'Yan Depo'); yalnizca portfoyun tamamiysa bos birak. "
            "Kirilim degerini bos birakma -- o zaman portfoy geneliyle karisir."
        ),
    )
    period: str | None = Field(default=None, description="Donem, or. '2026-03'.")


class Action(BaseModel):
    """Somut, sahiplenilebilir bir aksiyon onerisi."""

    priority: Priority
    title: str = Field(description="Tek cumlelik, emir kipinde eylem basligi.")
    rationale: str = Field(description="Neden simdi ve neden bu urun/kayit icin.")
    evidence: list[Evidence] = Field(
        min_length=1, description="Bu aksiyonu dogrulayan, tablolardan alinmis sayilar."
    )
    owner: str = Field(description="Sorumlu departman.")
    horizon: Horizon
    expected_impact_tl: float | None = Field(
        default=None, description="Parasal etki tahmini; hesaplanamiyorsa bos birak."
    )


class PeriodAnalysis(BaseModel):
    """Tek bir donemin analizi.

    `delta_vs_prev` bilerek zorunlu: modelin her donem icin ayni genel metni
    uretmesini engelleyip bir onceki doneme gore *ne degistigini* soylemeye
    mecbur birakir. Donemsel farklilasmanin sema tarafindaki garantisi budur.
    """

    period: str
    headline: str = Field(description="Bu donemi tek cumlede ozetleyen baslik.")
    delta_vs_prev: str = Field(
        description=(
            "Bir onceki doneme gore somut olarak ne degisti. Ilk donemde "
            "baslangic durumunu tarif et. Genel ifade degil, sayiya dayali fark."
        )
    )
    dominant_dynamics: list[str] = Field(
        description="Bu donemi belirleyen dinamikler (verilen listeden secilir)."
    )
    actions: list[Action] = Field(description="Bu doneme ozgu aksiyonlar.")
    watch_items: list[str] = Field(
        default_factory=list, description="Henuz aksiyon gerektirmeyen ama izlenmesi gerekenler."
    )


class RiskHighlight(BaseModel):
    entity: str
    title: str
    why_it_matters: str
    evidence: list[Evidence] = Field(min_length=1)


class ExecutiveSummary(BaseModel):
    """Yonetime hitap eden ust duzey sentez."""

    headline: str = Field(description="Yonetimin ilk okuyacagi tek cumle.")
    situation: str = Field(description="Genel durum: 2-4 cumle, sayiya dayali.")
    period_narrative: str = Field(
        description=(
            "Alti donemin hikayesi: nereden nereye gelindi, kirilma noktalari "
            "hangi donemlerde yasandi."
        )
    )
    top_risks: list[RiskHighlight] = Field(description="En kritik riskler, oncelik sirasiyla.")
    opportunities: list[RiskHighlight] = Field(
        default_factory=list, description="Degerlendirilmesi gereken firsatlar."
    )
    strategic_actions: list[Action] = Field(description="Yonetim seviyesinde stratejik aksiyonlar.")


class QAAnswer(BaseModel):
    """Serbest soru-cevap yaniti."""

    answer: str = Field(description="Soruya dogrudan, Turkce yanit.")
    evidence: list[Evidence] = Field(
        default_factory=list, description="Yaniti destekleyen, tablolardan alinmis sayilar."
    )
    confidence: Confidence
    caveats: list[str] = Field(
        default_factory=list,
        description="Yanitin sinirlari; veri yetersizse veya soru kapsam disiysa burada belirt.",
    )
