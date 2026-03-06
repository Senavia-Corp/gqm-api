# src/services/reports/timeline_report_pdf.py
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

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
    HRFlowable,
)
from reportlab.lib.utils import ImageReader

# ---------------------------------------------------------------------------
# Brand palette — identical to financial_report_pdf.py
# ---------------------------------------------------------------------------
GQM_GREEN    = colors.HexColor("#0B2E1E")
GQM_GREEN_2  = colors.HexColor("#0F3A27")
GQM_ORANGE   = colors.HexColor("#F28C00")
GQM_YELLOW   = colors.HexColor("#F2C100")
LIGHT_BG     = colors.HexColor("#F6F7F8")
CARD_BORDER  = colors.HexColor("#D9E1DD")
TABLE_HEADER = colors.HexColor("#EDF3F0")
TABLE_GRID   = colors.HexColor("#DCE6E1")
TEXT_MUTED   = colors.HexColor("#5B6B63")
EMERALD      = colors.HexColor("#059669")
ORANGE_ACC   = colors.HexColor("#EA580C")
BLUE_ACC     = colors.HexColor("#2563EB")
PURPLE_ACC   = colors.HexColor("#7C3AED")
RED_ACC      = colors.HexColor("#DC2626")

CATEGORY_LABELS = {
    "created":       "Created",
    "updated":       "Updated",
    "deleted":       "Deleted",
    "synced_podio":  "Podio Sync",
    "status_change": "Status Change",
    "other":         "Other",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fit_logo(path: str, max_w: float, max_h: float) -> Image:
    img = ImageReader(path)
    iw, ih = img.getSize()
    scale = min(max_w / float(iw), max_h / float(ih))
    return Image(path, width=iw * scale, height=ih * scale)


# ---------------------------------------------------------------------------
# Style factory — mirrors _make_styles() in financial_report_pdf.py exactly
# ---------------------------------------------------------------------------

def _make_styles() -> dict:
    base = getSampleStyleSheet()

    H1 = ParagraphStyle(
        "TH1", parent=base["Title"],
        fontName="Helvetica-Bold", fontSize=17, leading=20,
        textColor=colors.white, alignment=1, spaceAfter=2,
    )
    SmallWhite = ParagraphStyle(
        "TSmallWhite", parent=base["Normal"],
        fontName="Helvetica", fontSize=8, leading=10,
        textColor=colors.white, alignment=2,
    )
    SectionTitle = ParagraphStyle(
        "TSectionTitle", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=11, leading=13,
        textColor=GQM_GREEN, spaceBefore=10, spaceAfter=5,
    )
    Muted = ParagraphStyle(
        "TMuted", parent=base["Normal"],
        fontName="Helvetica", fontSize=8, leading=10,
        textColor=TEXT_MUTED, spaceAfter=4,
    )
    CardLabel = ParagraphStyle(
        "TCardLabel", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=GQM_GREEN, spaceAfter=2,
    )
    CardValue = ParagraphStyle(
        "TCardValue", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=16, leading=18,
        textColor=colors.black, spaceAfter=0,
    )
    CardSub = ParagraphStyle(
        "TCardSub", parent=base["Normal"],
        fontName="Helvetica", fontSize=7, leading=9,
        textColor=TEXT_MUTED, spaceAfter=0,
    )
    TableCell = ParagraphStyle(
        "TTableCell", parent=base["Normal"],
        fontName="Helvetica", fontSize=7.5, leading=9,
        textColor=colors.black,
    )
    TableCellMuted = ParagraphStyle(
        "TTableCellMuted", parent=base["Normal"],
        fontName="Helvetica", fontSize=7.5, leading=9,
        textColor=TEXT_MUTED,
    )
    TableHeader = ParagraphStyle(
        "TTableHeader", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=GQM_GREEN,
    )

    return {
        "H1": H1,
        "SmallWhite": SmallWhite,
        "SectionTitle": SectionTitle,
        "Muted": Muted,
        "CardLabel": CardLabel,
        "CardValue": CardValue,
        "CardSub": CardSub,
        "TableCell": TableCell,
        "TableCellMuted": TableCellMuted,
        "TableHeader": TableHeader,
    }


# ---------------------------------------------------------------------------
# Chart: activity over time
# ---------------------------------------------------------------------------

def _make_activity_chart(activity_over_time: list[dict], period: str) -> bytes:
    labels = [r["label"] for r in activity_over_time]
    counts = [r["count"] for r in activity_over_time]

    # For month view show only days with activity to reduce clutter
    if period == "month":
        non_zero = [(l, c) for l, c in zip(labels, counts) if c > 0]
        if non_zero:
            labels, counts = zip(*non_zero)
            labels, counts = list(labels), list(counts)

    if not counts or not any(c > 0 for c in counts):
        fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=150)
        ax.text(0.5, 0.5, "No activity in this period",
                ha="center", va="center", transform=ax.transAxes,
                color="#888", fontsize=11)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return buf.getvalue()

    max_v      = max(counts)
    bar_colors = ["#F28C00" if c == max_v else "#0B2E1E" for c in counts]

    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.bar(range(len(labels)), counts, color=bar_colors, alpha=0.88, width=0.6, zorder=3)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#E5E7EB")
    ax.spines["bottom"].set_color("#E5E7EB")
    ax.grid(axis="y", color="#F3F4F6", linewidth=0.8, zorder=0)
    ax.tick_params(axis="both", labelsize=7, colors="#6B7280")
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.set_ylabel("Events", fontsize=7, color="#6B7280")

    period_titles = {
        "day":   "Hourly Activity Distribution",
        "week":  "Daily Activity — This Week",
        "month": "Daily Activity — This Month",
    }
    ax.set_title(period_titles.get(period, "Activity Over Time"),
                 fontsize=10, fontweight="bold", pad=8, color="#111827")

    rotate = len(labels) > 10
    ax.set_xticks(list(range(len(labels))))
    ax.set_xticklabels(labels,
                       rotation=45 if rotate else 0,
                       ha="right" if rotate else "center",
                       fontsize=6.5)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_header(data: dict, styles: dict, *, logo_path: str | None = None) -> list:
    """
    3-column header: logo left | title centered | meta right.
    Followed by orange accent line.
    Mirrors _build_header() in financial_report_pdf.py exactly.
    """
    period_label = data["period"].capitalize()
    start        = data["date_range"]["start"][:10]
    end          = data["date_range"]["end"][:10]
    job_id       = data["job_id"]
    job_type     = data.get("job_type") or "—"
    generated    = datetime.now().strftime("%Y-%m-%d %H:%M")

    meta_line = (
        f"Job: {job_id}  •  Type: {job_type}  •  Period: {period_label}  •  "
        f"{start} → {end}  •  Generated: {generated}"
    )

    logo_cell: object = Paragraph("", getSampleStyleSheet()["Normal"])
    if logo_path:
        try:
            p = Path(logo_path)
            if p.exists():
                logo_cell = _fit_logo(str(p), max_w=1.55 * inch, max_h=0.75 * inch)
        except Exception:
            pass

    header_tbl = Table(
        [[logo_cell,
          Paragraph("Activity Timeline<br/>Report", styles["H1"]),
          Paragraph(meta_line, styles["SmallWhite"])]],
        colWidths=[1.7 * inch, 3.5 * inch, 2.4 * inch],
        rowHeights=[0.85 * inch],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), GQM_GREEN),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",         (0, 0), (0,  0),  "LEFT"),
        ("ALIGN",         (1, 0), (1,  0),  "CENTER"),
        ("ALIGN",         (2, 0), (2,  0),  "RIGHT"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    accent = Table([[""]], colWidths=[7.9 * inch], rowHeights=[0.07 * inch])
    accent.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GQM_ORANGE)]))

    return [header_tbl, accent, Spacer(1, 10)]


def _build_summary_cards(data: dict, styles: dict) -> list:
    """
    4 KPI cards in a single row.
    Mirrors _build_summary_cards() in financial_report_pdf.py exactly.
    """
    summary  = data["summary"]
    total    = summary["total_events"]
    by_cat   = summary.get("by_category", {})
    by_src   = summary.get("by_source", {})

    created  = by_cat.get("created", 0)
    updated  = by_cat.get("updated", 0)
    deleted  = by_cat.get("deleted", 0)
    statuses = by_cat.get("status_change", 0)
    synced   = by_cat.get("synced_podio", 0)
    other    = by_cat.get("other", 0)
    app_src  = by_src.get("app", 0)
    podio    = by_src.get("podio", 0)
    active   = len([v for v in by_cat.values() if v > 0])

    def card(label: str, value: str, sub: str = "", accent: colors.Color = GQM_GREEN):
        return [
            Paragraph(label, styles["CardLabel"]),
            Spacer(1, 3),
            Paragraph(
                f'<font color="{accent.hexval()}">{value}</font>',
                styles["CardValue"],
            ),
            Paragraph(sub, styles["CardSub"]),
        ]

    row = [
        card("Total Events",
             str(total),
             f"App: {app_src}  •  Podio: {podio}",
             EMERALD),
        card("Created / Updated",
             f"{created} / {updated}",
             f"Deleted: {deleted}",
             BLUE_ACC),
        card("Status Changes",
             str(statuses),
             f"Podio Syncs: {synced}",
             ORANGE_ACC),
        card("Other Actions",
             str(other),
             f"Active categories: {active}",
             PURPLE_ACC),
    ]

    tbl = Table([row], colWidths=[1.9 * inch] * 4)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.white),
        ("BOX",           (0, 0), (-1, -1), 1, CARD_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, CARD_BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))

    return [
        Paragraph("Summary", styles["SectionTitle"]),
        Paragraph("Activity breakdown for the selected job and period.", styles["Muted"]),
        tbl,
        Spacer(1, 12),
    ]


def _build_category_table(data: dict, styles: dict) -> list:
    by_cat = data["summary"].get("by_category", {})
    total  = max(data["summary"]["total_events"], 1)

    header = [
        Paragraph("Category",   styles["TableHeader"]),
        Paragraph("Events",     styles["TableHeader"]),
        Paragraph("Share",      styles["TableHeader"]),
    ]
    rows = [header]
    for cat, label in CATEGORY_LABELS.items():
        count = by_cat.get(cat, 0)
        pct   = count / total * 100
        rows.append([
            Paragraph(label,         styles["TableCell"]),
            Paragraph(str(count),    styles["TableCell"]),
            Paragraph(f"{pct:.1f}%", styles["TableCellMuted"]),
        ])

    col_w = [3.6 * inch, 1.4 * inch, 1.5 * inch]
    tbl = Table(rows, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEADER),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  GQM_GREEN),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -1), 0.4, TABLE_GRID),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))

    return [
        KeepTogether([
            Paragraph("Activity by Category", styles["SectionTitle"]),
            Paragraph("Totals grouped by action type.", styles["Muted"]),
            tbl,
        ]),
        Spacer(1, 10),
    ]


def _build_chart_section(data: dict, styles: dict) -> list:
    chart_bytes = _make_activity_chart(data["activity_over_time"], data["period"])
    chart_img   = Image(io.BytesIO(chart_bytes), width=7.2 * inch, height=3.0 * inch)

    period_label = {
        "day":   "Hourly Activity",
        "week":  "Daily Activity — This Week",
        "month": "Daily Activity — This Month",
    }.get(data["period"], "Activity Over Time")

    return [
        KeepTogether([
            Paragraph(period_label, styles["SectionTitle"]),
            Paragraph(
                "Each bar represents the number of events in that time bucket. "
                "The peak bar is highlighted in orange.",
                styles["Muted"],
            ),
            Spacer(1, 4),
            chart_img,
        ]),
        Spacer(1, 10),
    ]


def _build_timeline_table(data: dict, styles: dict) -> list:
    entries = data.get("timeline", [])

    header = [
        Paragraph("Date / Time", styles["TableHeader"]),
        Paragraph("Action",      styles["TableHeader"]),
        Paragraph("Details",     styles["TableHeader"]),
        Paragraph("By",          styles["TableHeader"]),
        Paragraph("Source",      styles["TableHeader"]),
    ]
    rows = [header]

    for e in entries:
        dt_raw = e.get("datetime") or ""
        try:
            dt_str = datetime.fromisoformat(dt_raw).strftime("%b %d  %H:%M")
        except Exception:
            dt_str = dt_raw[:16] if dt_raw else "—"

        action = e.get("action") or "—"
        desc   = e.get("description") or ""
        member = e.get("member_name") or e.get("member_id") or "—"
        source = e.get("source", "App")

        if len(desc) > 90:
            desc = desc[:87] + "…"

        src_color = PURPLE_ACC.hexval() if source == "Podio" else EMERALD.hexval()

        rows.append([
            Paragraph(dt_str, styles["TableCellMuted"]),
            Paragraph(action, styles["TableCell"]),
            Paragraph(desc,   styles["TableCellMuted"]),
            Paragraph(member, styles["TableCell"]),
            Paragraph(
                f'<font color="{src_color}"><b>{source}</b></font>',
                styles["TableCell"],
            ),
        ])

    col_w = [0.95*inch, 1.55*inch, 2.25*inch, 1.05*inch, 0.7*inch]

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEADER),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  GQM_GREEN),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -1), 0.4, TABLE_GRID),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))

    if not entries:
        return [
            Paragraph("Chronological Timeline", styles["SectionTitle"]),
            Paragraph("No events recorded in this period.", styles["Muted"]),
            Spacer(1, 10),
        ]

    return [
        KeepTogether([
            Paragraph("Chronological Timeline", styles["SectionTitle"]),
            Paragraph(
                f"{len(entries)} event(s) recorded in the selected period.",
                styles["Muted"],
            ),
            tbl,
        ]),
        Spacer(1, 10),
    ]


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_timeline_pdf(data: dict, *, logo_path: str | None = None) -> bytes:
    """
    Receives the dict from timeline_metrics_service.get_timeline_metrics_data()
    and returns PDF bytes. Structure and style mirror financial_report_pdf.py.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.55 * inch,
        title=f"Activity Timeline Report – {data.get('job_id', '')}",
        author="GQM Service",
    )

    styles = _make_styles()
    story  = []

    story.extend(_build_header(data, styles, logo_path=logo_path))
    story.extend(_build_summary_cards(data, styles))
    story.extend(_build_category_table(data, styles))
    story.extend(_build_chart_section(data, styles))
    story.extend(_build_timeline_table(data, styles))

    # Page number footer — identical to financial_report_pdf.py
    def _on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawRightString(7.9 * inch, 0.35 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()