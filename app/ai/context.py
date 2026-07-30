"""AI baglaminin insasi.

Modelin gordugu *her sayi* bu modulden gecer ve hepsi Polars tarafindan
hesaplanmistir. Ham CSV asla modele verilmez. Bu, "AI sayi uydurmasin"
kuralinin uygulama tarafindaki karsiligi: model hesaplayamaz, cunku
hesaplayacagi ham veriye erisimi yoktur.

Baglam iki parcaya ayrilir:
    sabit  -- tum donemlerde ayni (tablolar + risk sicili) -> onbelleklenir
    degisken -- "su donemi analiz et" -> onbellek kirilma noktasindan sonra
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.models import AnalyticsResult, PeriodDelta, QualityReport
from app.domain.packs.base import DatasetPack

MAX_ENTITY_ROWS = 40
"""Entity tablosunda modele verilecek azami satir. Buyuk raporlarda risk
tasiyanlar oncelik alir; amac baglami sinirli ve alakali tutmak."""


# ---------------------------------------------------------------------------
# Markdown yardimcilari
# ---------------------------------------------------------------------------
def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "evet" if value else "hayir"
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.0f}".replace(",", ".")
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def markdown_table(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "_(veri yok)_"
    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(_fmt(row.get(col)) for col in columns) + " |" for row in rows]
    return "\n".join([header, divider, *body])


# ---------------------------------------------------------------------------
# Sistem promptu
# ---------------------------------------------------------------------------
def build_system_prompt(pack: DatasetPack) -> str:
    profile = pack.prompt_profile
    glossary = "\n".join(f"- **{k}**: {v}" for k, v in profile.kpi_glossary.items())
    dynamics = ", ".join(profile.dynamics)
    departments = ", ".join(profile.department_keys)

    return f"""{profile.persona}

Gorevin: bir {profile.domain_label} uzerinden yonetime hitap eden, aksiyona
donusebilir analiz uretmek. Okuyucun teknik degil; sayidan cok *ne yapmasi
gerektigini* bilmek istiyor.

## Degismez kurallar

1. **Hicbir sayiyi kendin hesaplama.** Sana verilen tablolardaki degerleri
   oldugu gibi kullan. Toplama, oranlama, yuzde cikarma yapma. Bir sayiya
   ihtiyacin varsa ve tablolarda yoksa, o iddiayi kurma.
1b. **Kapsama dikkat et.** Tablolarin bir kismi TUM DONEMLERI kapsar
   (or. "5 donemdir stok sifir"), bir kismi TEK BIR DONEMI. Seri geneline
   ait bir degeri tek bir doneme aitmis gibi anlatma. Bir donemi
   anlatirken o donemin anlik goruntu tablosunu kullan; seri toplamlarini
   yalnizca "alti donem boyunca" gibi acikca genel ifadelerle kullan.
2. **Her aksiyon kanit tasimali.** `evidence` alanina yazdigin her deger
   tablolarda birebir bulunmali; metrik adini da tablodaki teknik adiyla yaz.
   Kanitin `entity` alanina degerin KAPSAMINI yaz: tek kayitsa kodunu, bir
   kategori/depo kirilimiyse o boyutun adini, portfoyun tamamiysa bos birak.
   Kirilim degerini bos birakirsan portfoy geneliyle karisir ve kanit
   dogrulanamaz.
3. **Genel tavsiye yasak.** "Stoklari optimize edin" degil, hangi {profile.entity_noun},
   hangi departman, hangi zaman ufku.
4. **Duzgun Turkce yaz.** Turkce karakterleri eksiksiz kullan: c yerine c/ç,
   g yerine g/ğ, i yerine i/ı, o yerine o/ö, s yerine s/ş, u yerine u/ü --
   yani "Brüt Kâr", "çıkış", "dönem", "sipariş". Bu prompt teknik nedenlerle
   ASCII yazilmistir; ONU TAKLIT ETME. Sade, kisa cumleler; jargon yerine
   is dili.
5. Emin olmadigin yerde emin olmadigini soyle; uydurma.

## Aksiyon uslubu
{profile.action_style}

Sorumlu departman olarak yalnizca sunlari kullan: {departments}

## Donem dinamikleri
Bir donemi tarif ederken yalnizca su etiketleri kullan: {dynamics}

## Metrik sozlugu
{glossary}
"""


# ---------------------------------------------------------------------------
# Sabit baglam (onbelleklenir)
# ---------------------------------------------------------------------------
def build_shared_context(
    result: AnalyticsResult,
    pack: DatasetPack,
    quality: QualityReport | None = None,
) -> str:
    profile = pack.prompt_profile
    parts: list[str] = [
        f"# Veri Seti: {pack.title}",
        pack.description,
        "",
        f"- Donemler: {', '.join(result.periods)}",
        f"- Kayit sayisi ({profile.entity_noun_plural}): {result.entity_count}",
    ]

    if quality is not None:
        parts += [
            f"- Veri saglik puani: {quality.health_score}/100",
            f"- Islenen satir: {quality.clean_row_count} / {quality.raw_row_count}"
            f" (karantina: {quality.quarantined_row_count})",
        ]
        if quality.issues:
            parts.append("")
            parts.append("## Veri kalitesi notlari")
            parts.append("Analizini yaparken bunlari akilda tut; gerekiyorsa yorumunda belirt.")
            for issue in quality.issues[:8]:
                parts.append(
                    f"- [{issue.severity.value}] {issue.title} "
                    f"({issue.affected_rows} satir, islem: {issue.action.value})"
                )

    # --- donem tablosu ---
    period_cols = [pack.period_key] + [a.name for a in pack.period_aggregates]
    parts += [
        "",
        "## Donemsel portfoy ozeti",
        markdown_table(result.period_rows, period_cols),
    ]

    # --- boyut kirilimi ---
    if result.dimension_rows:
        dim_cols = ["dimension", "dimension_value", pack.period_key] + [
            a.name for a in pack.dimension_aggregates
        ]
        parts += [
            "",
            "## Boyut kirilimi",
            markdown_table(result.dimension_rows, dim_cols),
        ]

    # --- entity tablosu ---
    entity_cols = _entity_columns(pack)
    entity_rows = _prioritise_entities(result, pack)
    parts += [
        "",
        f"## {profile.entity_noun_plural.capitalize()} bazinda ozet — TUM DONEMLERIN TOPLAMI",
        (
            "> Dikkat: bu tablodaki degerler alti donemin tamamina aittir, tek bir "
            "doneme degil. Ornegin 'sifir_stok_donem = 3' demek *seri boyunca "
            "toplam 3 donemde* stok sifir olmus demektir; analiz ettigin donemde "
            "stogun sifir oldugu anlamina GELMEZ. Tek bir donemin degerleri icin "
            "o donemin sorusundaki anlik goruntu tablosuna bak."
        ),
        "",
        markdown_table(entity_rows, entity_cols),
    ]

    # --- risk sicili ---
    parts += ["", "## Hesaplanmis risk sicili", _risk_register(result)]

    return "\n".join(parts)


def _entity_columns(pack: DatasetPack) -> list[str]:
    """AI'a gosterilecek entity kolonlari.

    `internal` isaretli toplulastirmalar disarida birakilir: bunlar motorun
    risk baslangic donemini bulmak icin hesapladigi yardimci kolonlar ve
    bilgileri zaten risk sicilinde yer aliyor. Tabloda tekrar etmek yalnizca
    onbellege yazilan token sayisini -- yani maliyeti -- buyutur.
    """
    base = [pack.entity_key, pack.entity_label_key, *pack.dimensions]
    return base + [a.name for a in pack.entity_aggregates if not a.internal]


def _prioritise_entities(result: AnalyticsResult, pack: DatasetPack) -> list[dict[str, Any]]:
    """Riskli kayitlar once; baglam sinirini asarsak onemli olan kaybolmasin."""
    if len(result.entity_rows) <= MAX_ENTITY_ROWS:
        return list(result.entity_rows)

    risky = {r.entity for r in result.risks}
    key = pack.entity_key
    ordered = sorted(result.entity_rows, key=lambda row: str(row.get(key)) not in risky)
    return ordered[:MAX_ENTITY_ROWS]


def _period_snapshot(period: str, result: AnalyticsResult, pack: DatasetPack) -> str:
    """Analiz edilen donemin kayit bazli anlik goruntusu.

    Bilincli olarak degisken (onbelleklenmeyen) kisma konuyor: her donem icin
    farkli. Maliyeti dusuk (~400 token) ama modelin seri toplamlarini tek bir
    doneme atfetme egilimini kokunden kaldiriyor -- cunku ihtiyaci olan sayi
    artik elinde.
    """
    if not pack.snapshot_columns:
        return ""

    rows = [row for row in result.series_rows if row.get(pack.period_key) == period]
    if not rows:
        return ""

    columns = [pack.entity_key, pack.entity_label_key, *pack.snapshot_columns]
    available = [c for c in columns if any(c in row for row in rows)]
    return markdown_table(rows, available)


def _risk_register(result: AnalyticsResult) -> str:
    if not result.risks:
        return "_(motor herhangi bir risk tespit etmedi)_"

    lines: list[str] = []
    for risk in result.risks:
        impact = (
            f" | tahmini etki: {risk.financial_impact_tl:,.0f} TL".replace(",", ".")
            if risk.financial_impact_tl
            else ""
        )
        onset = f" | ilk gorulme: {risk.first_seen_period}" if risk.first_seen_period else ""
        evidence = ", ".join(
            f"{e.metric}={_fmt(e.value)}{e.unit if e.unit != 'sayi' else ''}" for e in risk.evidence
        )
        lines.append(
            f"- **[{risk.severity.value.upper()}] {risk.code}** -- {risk.entity} "
            f"{risk.entity_label}{impact}{onset}\n"
            f"  - Durum: {risk.narrative}\n"
            f"  - Motor onerisi: {risk.recommendation}\n"
            f"  - Kanit: {evidence}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Degisken kisim -- donem sorusu
# ---------------------------------------------------------------------------
def build_period_question(
    period: str, delta: PeriodDelta | None, result: AnalyticsResult, pack: DatasetPack
) -> str:
    profile = pack.prompt_profile
    parts = [
        f"# Analiz edilecek donem: {period}",
        "",
        "Yukaridaki tablolarin TAMAMI elinde; ama su an yalnizca bu donemi analiz et.",
        "",
    ]

    if delta is not None:
        if delta.previous_period:
            parts.append(f"## {delta.previous_period} -> {period} degisimi")
        else:
            parts.append("## Baslangic donemi (karsilastirilacak onceki donem yok)")

        if delta.metrics:
            parts.append("Bu donemin portfoy degerleri:")
            for metric in delta.metrics:
                parts.append(f"- {metric.label}: {_fmt(metric.value)} {metric.unit.value}")

        # Metrik adlarini teknik haliyle veriyoruz: model kanit yazarken bu adi
        # birebir kopyalasin diye. Sadece etiket verirsek adi kendi uyduruyor ve
        # dogrulama katmani gecerli bir kaniti bulamiyor.
        if delta.movers_up:
            parts.append("")
            parts.append("En cok artanlar:")
            for m in delta.movers_up:
                parts.append(
                    f"- {m.entity} | metrik `{m.metric}` = +{_fmt(m.value)} {m.unit.value}"
                )
        if delta.movers_down:
            parts.append("")
            parts.append("En cok azalanlar:")
            for m in delta.movers_down:
                parts.append(f"- {m.entity} | metrik `{m.metric}` = {_fmt(m.value)} {m.unit.value}")

        if delta.new_risks:
            parts.append("")
            parts.append(
                "Bu donemde ILK KEZ ortaya cikan risk tipleri: " + ", ".join(delta.new_risks)
            )

    period_risks = result.risks_for_period(period)
    if period_risks:
        parts.append("")
        parts.append("Bu donemde baslayan riskler:")
        for risk in period_risks:
            parts.append(f"- {risk.code} / {risk.entity} {risk.entity_label}: {risk.narrative}")

    snapshot = _period_snapshot(period, result, pack)
    if snapshot:
        parts += [
            "",
            f"## {period} anlik goruntusu — SADECE BU DONEMIN DEGERLERI",
            (
                "Bu donemi anlatirken kayit bazli sayilari BURADAN al. Yukaridaki "
                "ozet tablosu tum donemleri kapsiyor; bu tablo yalnizca "
                f"{period} donemini."
            ),
            "",
            snapshot,
        ]

    parts += [
        "",
        "## Beklenen cikti",
        "Bu doneme OZGU analiz uret. Diger donemlerde de gecerli olacak genel "
        "ifadelerden kacin -- `delta_vs_prev` alaninda somut olarak neyin degistigini yaz.",
        f"Aksiyonlar bu donemin dinamiklerinden dogmali ve ilgili {profile.entity_noun} "
        "kodunu icermeli.",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Degisken kisim -- yonetici sentezi
# ---------------------------------------------------------------------------
def build_summary_question(period_analyses: Sequence[Any], pack: DatasetPack) -> str:
    parts = [
        "# Yonetici ozeti",
        "",
        "Asagida her donem icin uretilmis analizler var. Bunlari ve yukaridaki "
        "tablolari kullanarak yonetime hitap eden bir sentez uret.",
        "",
    ]
    for analysis in period_analyses:
        parts.append(f"## {analysis.period}")
        parts.append(f"- Baslik: {analysis.headline}")
        parts.append(f"- Degisim: {analysis.delta_vs_prev}")
        parts.append(f"- Dinamikler: {', '.join(analysis.dominant_dynamics)}")
        for action in analysis.actions:
            parts.append(f"- Aksiyon [{action.priority}] {action.title} ({action.owner})")
        parts.append("")

    parts += [
        "## Beklenen cikti",
        "- `period_narrative` alaninda alti donemin hikayesini anlat: nereden nereye "
        "gelindi, kirilma hangi donemde oldu.",
        "- `strategic_actions` tekil operasyonel islerin tekrari olmasin; yonetim "
        "seviyesinde karar gerektiren konular olsun.",
        "- Her kanit yukaridaki tablolardan alinmis olmali.",
    ]
    return "\n".join(parts)


def build_qa_question(question: str) -> str:
    return f"""# Kullanici sorusu

{question}

## Yanit kurallari
- Yalnizca yukaridaki tablolara dayanarak yanitla.
- Tablolarda olmayan bir sey soruluyorsa bunu acikca soyle ve `confidence` degerini
  "dusuk" yap; tahmin uretme.
- Kullandigin her sayiyi `evidence` alaninda metrik adiyla birlikte ver.
- Yanitin kisa ve dogrudan olsun.
"""
