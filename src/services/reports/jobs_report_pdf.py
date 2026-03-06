# src/services/reports/jobs_report_pdf.py
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # ✅ serverless safe
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    KeepTogether,
)
from reportlab.lib.utils import ImageReader


# ----------------------------
# Branding colors (GQM vibe)
# ----------------------------
GQM_GREEN = colors.HexColor("#0B2E1E")
GQM_GREEN_2 = colors.HexColor("#0F3A27")
GQM_ORANGE = colors.HexColor("#F28C00")
GQM_YELLOW = colors.HexColor("#F2C100")
LIGHT_BG = colors.HexColor("#F6F7F8")
CARD_BORDER = colors.HexColor("#D9E1DD")
TABLE_HEADER_BG = colors.HexColor("#EDF3F0")
TABLE_GRID = colors.HexColor("#DCE6E1")
TEXT_MUTED = colors.HexColor("#5B6B63")


def _fit_logo(path: str, max_w: float, max_h: float) -> Image:
    """
    Carga el logo manteniendo aspect ratio (sin deformar).
    """
    img = ImageReader(path)
    iw, ih = img.getSize()

    scale = min(max_w / float(iw), max_h / float(ih))
    w = iw * scale
    h = ih * scale

    return Image(path, width=w, height=h)


def _make_donut_png_bytes(rows: list[dict], top_n: int = 8) -> bytes:
    """
    Donut chart con los status más relevantes.
    - NO pinta porcentajes sobre la gráfica.
    - Los porcentajes van en la leyenda.
    """
    data = [(r["status"], int(r["count"])) for r in rows if int(r["count"]) > 0]
    data.sort(key=lambda x: x[1], reverse=True)

    if not data:
        labels = ["No data"]
        values = [1]
    else:
        main = data[:top_n]
        rest = data[top_n:]
        labels = [x[0] for x in main]
        values = [x[1] for x in main]
        if rest:
            labels.append("Other")
            values.append(sum(x[1] for x in rest))

    total = sum(values) if values else 1
    pct_labels = [f"{lab}  ({(v/total*100):.1f}%)" for lab, v in zip(labels, values)]

    fig = plt.figure(figsize=(6.6, 3.6), dpi=170)
    ax = fig.add_subplot(111)

    # donut
    wedges, _ = ax.pie(
        values,
        startangle=90,
        labels=None,           # ✅ no labels encima
        autopct=None,          # ✅ no % encima
        pctdistance=0.75,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1},
    )
    ax.axis("equal")

    # legend con % (derecha)
    ax.legend(
        wedges,
        pct_labels,
        title="Status",
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        frameon=False,
        fontsize=8,
        title_fontsize=9,
    )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def build_jobs_report_pdf_bytes(
    metrics: dict,
    *,
    company_name: str = "Company",
    logo_path: str | None = None,
) -> bytes:
    """
    Retorna bytes del PDF.
    metrics: output del service get_jobs_status_metrics_data()
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.55 * inch,
        title="Jobs Report",
        author=company_name,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    H1 = ParagraphStyle(
        "H1",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=20,
        textColor=colors.white,
        alignment=1,  # center
        spaceAfter=2,
    )
    SmallWhite = ParagraphStyle(
        "SmallWhite",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=1,
    )
    SectionTitle = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=GQM_GREEN,
        spaceBefore=10,
        spaceAfter=6,
    )
    Muted = ParagraphStyle(
        "Muted",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        textColor=TEXT_MUTED,
        spaceAfter=6,
    )
    CardLabel = ParagraphStyle(
        "CardLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=GQM_GREEN,
        spaceAfter=2,
    )
    CardValue = ParagraphStyle(
        "CardValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=20,
        textColor=colors.black,
        spaceAfter=0,
    )
    CardText = ParagraphStyle(
        "CardText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.black,
        spaceAfter=0,
    )

    story = []

    # ----------------------------
    # Header band (logo + title + meta)
    # ----------------------------
    generated = datetime.now()
    type_txt = metrics.get("type") or "ALL"
    year_txt = metrics.get("year") or "ALL"
    meta_line = f"Type: {type_txt}  •  Year: {year_txt}  •  Generated: {generated.strftime('%Y-%m-%d %H:%M')}"

    # Row with background color using Table
    logo_cell = Paragraph("", styles["Normal"])
    if logo_path:
        p = Path(logo_path)
        if p.exists():
            logo_cell = _fit_logo(str(p), max_w=1.55 * inch, max_h=0.75 * inch)

    title_cell = Paragraph("Jobs Status Distribution", H1)
    meta_cell = Paragraph(meta_line, SmallWhite)

    header_tbl = Table(
        [[logo_cell, title_cell, meta_cell]],
        colWidths=[1.7 * inch, 3.7 * inch, 2.2 * inch],
        rowHeights=[0.85 * inch],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GQM_GREEN),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header_tbl)

    # thin accent line
    accent = Table([[""]], colWidths=[7.9 * inch], rowHeights=[0.08 * inch])
    accent.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GQM_ORANGE)]))
    story.append(accent)

    story.append(Spacer(1, 12))

    # ----------------------------
    # Summary card
    # ----------------------------
    total = int(metrics.get("total") or 0)

    card_left = [
        Paragraph("Total Jobs", CardLabel),
        Spacer(1, 4),  # ✅ más aire entre label y número
        Paragraph(str(total), CardValue),
    ]

    card_mid = [
        Paragraph("Filters", CardLabel),
        Spacer(1, 4),
        Paragraph(f"Type: <b>{type_txt}</b><br/>Year: <b>{year_txt}</b>", CardText),
    ]

    card_right = [
        Paragraph("About", CardLabel),
        Spacer(1, 4),
        Paragraph(
            "This report summarizes the Jobs pipeline for the selected filters. "
            "It includes status distribution, top statuses, and a visual breakdown.",
            CardText
        ),
    ]

    card_tbl = Table(
        [[card_left, card_mid, card_right]],
        colWidths=[2.1 * inch, 1.5 * inch, 4.3 * inch],
    )
    card_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 1, CARD_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(card_tbl)
    story.append(Spacer(1, 14))

    # ----------------------------
    # Status distribution table
    # ----------------------------
    rows = metrics.get("rows") or []

    story.append(Paragraph("Status Distribution", SectionTitle))
    story.append(Paragraph("Counts and percent share per status.", Muted))

    table_data = [["Status", "Count", "%"]]  # ✅ sin <b> para evitar que se impriman tags
    for r in rows:
        table_data.append([r["status"], str(int(r["count"])), f'{float(r["pct"]):.2f}%'])

    dist_tbl = Table(table_data, colWidths=[5.2 * inch, 1.1 * inch, 0.9 * inch])
    dist_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), GQM_GREEN),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(dist_tbl)
    story.append(Spacer(1, 14))

    # ----------------------------
    # Top 5 + Pie chart block (kept together)
    # ----------------------------
    top5 = sorted(rows, key=lambda x: int(x["count"]), reverse=True)[:5]
    top5_data = [["Status", "Count"]]
    for r in top5:
        top5_data.append([r["status"], str(int(r["count"]))])

    top5_tbl = Table(top5_data, colWidths=[6.0 * inch, 1.2 * inch])
    top5_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), GQM_GREEN),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))

    donut_png = _make_donut_png_bytes(rows, top_n=8)
    donut_img = Image(io.BytesIO(donut_png), width=7.2 * inch, height=3.8 * inch)

    # ✅ KeepTogether evita que “Top 5” quede partido por page-break
    # ✅ y evita el espacio raro donde queda solo el título o media tabla
    story.append(KeepTogether([
        Paragraph("Top 5 Statuses", SectionTitle),
        Paragraph("Most frequent statuses by count.", Muted),
        top5_tbl,
        Spacer(1, 14),
        Paragraph("Status Share (Donut Chart)", SectionTitle),
        Paragraph("Grouped by the most relevant statuses. Percentages shown in legend.", Muted),
        donut_img,
    ]))

    # ----------------------------
    # Footer: page number
    # ----------------------------
    def _on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawRightString(7.9 * inch, 0.35 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()