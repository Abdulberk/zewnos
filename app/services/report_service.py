"""Paylasilabilir PDF rapor uretimi (bonus).

Yonetime gonderilebilecek tek dosyalik cikti: KPI'lar, donemsel hikaye, risk
sicili ve veri kalitesi notlari. AI analizi onbellekte varsa yonetici ozeti ve
doneme ozgu aksiyonlar da rapora girer; yoksa rapor yalnizca hesaplanmis
verilerle uretilir (AI olmadan da calisir).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.models import AnalyticsResult, QualityReport, Severity
from app.domain.packs.base import DatasetPack

# --- renkler ---------------------------------------------------------------
INK = colors.HexColor("#1A1D23")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
BAND = colors.HexColor("#F6F7F9")
SEVERITY_COLORS = {
    Severity.KRITIK: colors.HexColor("#B42318"),
    Severity.YUKSEK: colors.HexColor("#B54708"),
    Severity.ORTA: colors.HexColor("#854D0E"),
    Severity.DUSUK: colors.HexColor("#3F6212"),
    Severity.BILGI: colors.HexColor("#1F6FEB"),
}

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _register_fonts() -> None:
    """Turkce karakterleri destekleyen bir font bul.

    Helvetica'nin WinAnsi kodlamasinda s, g, i harfleri yok; bunlar olmadan
    rapor "Dosemelik" gibi cikar. Sirayla aday fontlar denenir.
    """
    global _FONT, _FONT_BOLD
    candidates = [
        ("DejaVuSans", "DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu"),
        ("Arial", "Arial-Bold", "C:/Windows/Fonts"),
    ]
    files = {
        "DejaVuSans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
        "Arial": ("arial.ttf", "arialbd.ttf"),
    }
    for regular, bold, directory in candidates:
        base = Path(directory)
        regular_file, bold_file = files[regular]
        if not (base / regular_file).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(regular, str(base / regular_file)))
            bold_path = base / bold_file
            if bold_path.exists():
                pdfmetrics.registerFont(TTFont(bold, str(bold_path)))
            else:
                bold = regular
            _FONT, _FONT_BOLD = regular, bold
            return
        except Exception:
            continue


_register_fonts()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t",
            parent=base["Title"],
            fontName=_FONT_BOLD,
            fontSize=20,
            leading=25,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "st",
            parent=base["Normal"],
            fontName=_FONT,
            fontSize=9.5,
            leading=13,
            textColor=MUTED,
            spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=_FONT_BOLD,
            fontSize=13,
            leading=17,
            textColor=INK,
            spaceBefore=16,
            spaceAfter=7,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base["Heading3"],
            fontName=_FONT_BOLD,
            fontSize=10.5,
            leading=14,
            textColor=INK,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "b",
            parent=base["Normal"],
            fontName=_FONT,
            fontSize=9.5,
            leading=14,
            textColor=INK,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "s",
            parent=base["Normal"],
            fontName=_FONT,
            fontSize=8.2,
            leading=11.5,
            textColor=MUTED,
        ),
        "cell": ParagraphStyle(
            "c",
            parent=base["Normal"],
            fontName=_FONT,
            fontSize=8.2,
            leading=11,
            textColor=INK,
        ),
    }


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}".replace(",", ".") + " TL"


def _table(rows: list[list[Any]], widths: list[float], *, header: bool = True) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        style += [
            ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
            ("BACKGROUND", (0, 0), (-1, 0), BAND),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
        ]
    table.setStyle(TableStyle(style))
    return table


def build_report(
    *,
    pack: DatasetPack,
    result: AnalyticsResult,
    quality: QualityReport,
    dataset_name: str,
    analysis: dict[str, Any] | None = None,
) -> bytes:
    """Tek dosyalik yonetici raporu uretir."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{pack.title} - Yönetici Raporu",
        author="Sonart Insight",
    )
    story: list[Any] = []
    content_width = doc.width

    # --- baslik ---
    story.append(Paragraph(pack.title, styles["title"]))
    story.append(
        Paragraph(
            f"Yönetici raporu &nbsp;·&nbsp; {dataset_name} &nbsp;·&nbsp; "
            f"{result.periods[0]} - {result.periods[-1]} &nbsp;·&nbsp; "
            f"{result.entity_count} kayıt &nbsp;·&nbsp; "
            f"üretim: {datetime.now(UTC).strftime('%d.%m.%Y %H:%M')} UTC",
            styles["subtitle"],
        )
    )

    # --- KPI seridi ---
    if result.headline_metrics:
        story.append(Paragraph(f"Son dönem ({result.periods[-1]}) göstergeleri", styles["h2"]))
        labels = [Paragraph(f"<b>{m.label}</b>", styles["cell"]) for m in result.headline_metrics]
        values = [
            Paragraph(
                f"{m.value:,.2f}".replace(",", " ").rstrip("0").rstrip(".") + f" {m.unit.value}",
                styles["cell"],
            )
            for m in result.headline_metrics
        ]
        width = content_width / max(1, len(labels))
        story.append(_table([labels, values], [width] * len(labels), header=True))

    # --- yonetici ozeti (AI) ---
    summary = (analysis or {}).get("summary")
    if summary:
        story.append(Paragraph("Yönetici özeti", styles["h2"]))
        story.append(Paragraph(f"<b>{summary['headline']}</b>", styles["body"]))
        story.append(Paragraph(summary["situation"], styles["body"]))
        story.append(Paragraph("<b>Altı dönemin hikayesi</b>", styles["h3"]))
        story.append(Paragraph(summary["period_narrative"], styles["body"]))

        if summary.get("strategic_actions"):
            story.append(Paragraph("Stratejik aksiyonlar", styles["h3"]))
            rows = [["Oncelik", "Aksiyon", "Sahip", "Ufuk", "Etki"]]
            for action in summary["strategic_actions"]:
                rows.append(
                    [
                        Paragraph(action["priority"].upper(), styles["cell"]),
                        Paragraph(action["title"], styles["cell"]),
                        Paragraph(action["owner"], styles["cell"]),
                        Paragraph(action["horizon"].replace("_", " "), styles["cell"]),
                        Paragraph(_money(action.get("expected_impact_tl")), styles["cell"]),
                    ]
                )
            story.append(
                _table(
                    rows,
                    [
                        content_width * 0.11,
                        content_width * 0.49,
                        content_width * 0.14,
                        content_width * 0.12,
                        content_width * 0.14,
                    ],
                )
            )

    # --- donemsel trend ---
    story.append(Paragraph("Dönemsel trend", styles["h2"]))
    headline_names = [a.name for a in pack.headline_aggregates]
    header = [Paragraph("<b>Dönem</b>", styles["cell"])] + [
        Paragraph(f"<b>{a.label}</b>", styles["cell"]) for a in pack.headline_aggregates
    ]
    rows = [header]
    for row in result.period_rows:
        cells = [Paragraph(str(row.get(pack.period_key, "")), styles["cell"])]
        for name in headline_names:
            value = row.get(name)
            text = "-" if value is None else f"{float(value):,.1f}".replace(",", ".")
            cells.append(Paragraph(text, styles["cell"]))
        rows.append(cells)
    column_width = content_width / len(header)
    story.append(_table(rows, [column_width] * len(header)))

    # --- risk sicili ---
    story.append(PageBreak())
    story.append(Paragraph("Risk sicili", styles["h2"]))
    total_impact = sum(r.financial_impact_tl or 0 for r in result.risks)
    story.append(
        Paragraph(
            f"Motor {len(result.risks)} risk tespit etti. Parasal etkisi tahmin "
            f"edilebilenlerin toplamı: <b>{_money(total_impact)}</b>.",
            styles["body"],
        )
    )
    rows = [
        [
            Paragraph("<b>Agirlik</b>", styles["cell"]),
            Paragraph("<b>Kayıt</b>", styles["cell"]),
            Paragraph("<b>Bulgu</b>", styles["cell"]),
            Paragraph("<b>İlk görülme</b>", styles["cell"]),
            Paragraph("<b>Etki</b>", styles["cell"]),
        ]
    ]
    for risk in result.risks:
        # hexval() "0xb42318" dondurur; reportlab '#rrggbb' bekler.
        color = f"#{SEVERITY_COLORS.get(risk.severity, INK).hexval()[2:]}"
        rows.append(
            [
                Paragraph(
                    f'<font color="{color}"><b>{risk.severity.value.upper()}</b></font>',
                    styles["cell"],
                ),
                Paragraph(f"{risk.entity}<br/>{risk.entity_label}", styles["cell"]),
                Paragraph(f"<b>{risk.title}</b><br/>{risk.narrative}", styles["cell"]),
                Paragraph(risk.first_seen_period or "-", styles["cell"]),
                Paragraph(_money(risk.financial_impact_tl), styles["cell"]),
            ]
        )
    story.append(
        _table(
            rows,
            [
                content_width * 0.09,
                content_width * 0.17,
                content_width * 0.49,
                content_width * 0.12,
                content_width * 0.13,
            ],
        )
    )

    # --- doneme ozgu aksiyonlar (AI) ---
    periods = (analysis or {}).get("periods") or []
    if periods:
        story.append(PageBreak())
        story.append(Paragraph("Döneme özgü analiz ve aksiyonlar", styles["h2"]))
        for period in periods:
            block: list[Any] = [
                Paragraph(f"{period['period']} — {period['headline']}", styles["h3"]),
                Paragraph(f"<i>Değişim:</i> {period['delta_vs_prev']}", styles["body"]),
            ]
            if period.get("dominant_dynamics"):
                block.append(
                    Paragraph(
                        "<i>Dinamikler:</i> " + ", ".join(period["dominant_dynamics"]),
                        styles["small"],
                    )
                )
            for action in period.get("actions", []):
                block.append(
                    Paragraph(
                        f"• <b>[{action['priority']}]</b> {action['title']} "
                        f"<font size=7.5 color='#6B7280'>({action['owner']} / "
                        f"{action['horizon'].replace('_', ' ')})</font>",
                        styles["body"],
                    )
                )
            story.append(KeepTogether(block))
            story.append(Spacer(1, 4))

    # --- veri kalitesi ---
    story.append(PageBreak())
    story.append(Paragraph("Veri kalitesi", styles["h2"]))
    story.append(
        Paragraph(
            f"Saglik puani <b>{quality.health_score}/100</b>. "
            f"{quality.raw_row_count} ham satirdan {quality.clean_row_count} tanesi "
            f"işlendi, {quality.quarantined_row_count} tanesi karantinaya alındı. "
            f"Kodlama: {quality.encoding_detected}.",
            styles["body"],
        )
    )
    rows = [
        [
            Paragraph("<b>Agirlik</b>", styles["cell"]),
            Paragraph("<b>Bulgu</b>", styles["cell"]),
            Paragraph("<b>Satır</b>", styles["cell"]),
            Paragraph("<b>Yapılan işlem</b>", styles["cell"]),
        ]
    ]
    for issue in quality.issues:
        detail = issue.detail
        if issue.samples:
            detail += (
                "<br/><font size=7.5 color='#6B7280'>" + "; ".join(issue.samples[:3]) + "</font>"
            )
        rows.append(
            [
                Paragraph(issue.severity.value.upper(), styles["cell"]),
                Paragraph(f"<b>{issue.title}</b><br/>{detail}", styles["cell"]),
                Paragraph(str(issue.affected_rows), styles["cell"]),
                Paragraph(issue.action.value, styles["cell"]),
            ]
        )
    story.append(
        _table(
            rows,
            [
                content_width * 0.10,
                content_width * 0.62,
                content_width * 0.09,
                content_width * 0.19,
            ],
        )
    )

    grounding = (analysis or {}).get("grounding")
    if grounding:
        story.append(Paragraph("AI ciktisinin veriye dayaniligi", styles["h2"]))
        story.append(
            Paragraph(
                f"AI'in urettigi {grounding['total_evidence']} kanittan "
                f"{grounding['verified_evidence']} tanesi hesaplanmış tablolarda "
                f"birebir dogrulandi "
                f"(<b>%{grounding['grounding_ratio'] * 100:.0f}</b>). "
                "Sayılar Polars tarafından hesaplanır; AI yalnızca yorumlar.",
                styles["body"],
            )
        )

    doc.build(story)
    return buffer.getvalue()
