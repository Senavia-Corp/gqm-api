# src/services/reports/financial_jobs_pdf.py
from __future__ import annotations
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
import matplotlib.ticker as mtick
import matplotlib.pyplot as plt

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")


# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------
GQM_GREEN = colors.HexColor("#145F3D")
GQM_GREEN_2 = colors.HexColor("#1E6445")
GQM_ORANGE = colors.HexColor("#F28C00")
LIGHT_BG = colors.HexColor("#F6F7F8")
LIGHT_GREEN = colors.HexColor("#DFF1E8")
CARD_BG = colors.HexColor("#F8FAF9")
CARD_BORDER = colors.HexColor("#D9E1DD")
TABLE_GRID = colors.HexColor("#DCE6E1")
TEXT_DARK = colors.HexColor("#1A1A1A")
TEXT_MUTED = colors.HexColor("#5B6B63")
EMERALD = colors.HexColor("#059669")
RED_ACC = colors.HexColor("#DC2626")
AMBER_ACC = colors.HexColor("#D97706")
BLUE_ACC = colors.HexColor("#2563EB")
PURPLE_ACC = colors.HexColor("#7C3AED")

MPL_GREEN = "#126942"
MPL_ORANGE = "#F28C00"
MPL_BORDER = "#DCE6E1"
MPL_MUTED = "#5B6B63"

PAGE_W = 7.7 * inch

# High DPI for crisp rendering at any zoom level
CHART_DPI = 220


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _fmt_pct(v) -> str:
    try:
        return f"{(float(v) * 100):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _fit_logo(path: str, max_w: float, max_h: float) -> Image:
    img = ImageReader(path)
    iw, ih = img.getSize()
    scale = min(max_w / float(iw), max_h / float(ih))
    return Image(path, width=iw * scale, height=ih * scale)


def _save_chart(fig) -> bytes:
    """Saves a matplotlib figure to bytes at high DPI with tight bbox."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=CHART_DPI)
    plt.close(fig)
    return buf.getvalue()


def _y_fmt(v, _) -> str:
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.0f}k"
    return f"${v:.0f}"


# ---------------------------------------------------------------------------
# Style factory
# ---------------------------------------------------------------------------

def _make_styles() -> dict:
    base = getSampleStyleSheet()
    s = {}

    s["MainTitle"] = ParagraphStyle("MT", parent=base["Title"],
                                    fontSize=18, textColor=GQM_GREEN, fontName="Helvetica-Bold",
                                    alignment=TA_LEFT, spaceAfter=2, leading=22)

    s["SubTitle"] = ParagraphStyle("ST", parent=base["Normal"],
                                   fontSize=8.5, textColor=TEXT_MUTED, fontName="Helvetica", spaceAfter=6)

    s["SectionHeader"] = ParagraphStyle("SH", parent=base["Normal"],
                                        fontSize=11, textColor=GQM_GREEN, fontName="Helvetica-Bold",
                                        spaceBefore=16, spaceAfter=8,
                                        borderLeftColor=GQM_ORANGE, borderLeftWidth=3, leftIndent=8, leading=14)

    s["Muted"] = ParagraphStyle("Mu", parent=base["Normal"],
                                fontSize=8, textColor=TEXT_MUTED, fontName="Helvetica", spaceAfter=4)

    s["CardLabel"] = ParagraphStyle("CL", parent=base["Normal"],
                                    fontSize=7.5, fontName="Helvetica-Bold", textColor=GQM_GREEN,
                                    alignment=TA_CENTER, leading=9)
    s["CardVal"] = ParagraphStyle("CV", parent=base["Normal"],
                                  fontSize=14, fontName="Helvetica-Bold", textColor=TEXT_DARK,
                                  alignment=TA_CENTER, leading=17)
    s["CardSub"] = ParagraphStyle("CS", parent=base["Normal"],
                                  fontSize=6.5, fontName="Helvetica", textColor=TEXT_MUTED,
                                  alignment=TA_CENTER, leading=8)

    s["THeader"] = ParagraphStyle("TH", parent=base["Normal"],
                                  fontSize=7.5, fontName="Helvetica-Bold", textColor=GQM_GREEN,
                                  alignment=TA_CENTER, leading=9)
    s["TCell"] = ParagraphStyle("TC",  parent=base["Normal"],
                                fontSize=6.5, fontName="Helvetica", textColor=TEXT_DARK, leading=9)
    s["TCellB"] = ParagraphStyle("TCB", parent=base["Normal"],
                                 fontSize=6.5, fontName="Helvetica-Bold", textColor=TEXT_DARK, leading=9)
    s["TCellR"] = ParagraphStyle("TCR", parent=base["Normal"],
                                 fontSize=6.5, fontName="Helvetica", textColor=TEXT_DARK,
                                 alignment=TA_RIGHT, leading=9)
    s["TCellRB"] = ParagraphStyle("TCRB", parent=base["Normal"],
                                  fontSize=6.5, fontName="Helvetica-Bold", textColor=TEXT_DARK,
                                  alignment=TA_RIGHT, leading=9)
    s["TCellC"] = ParagraphStyle("TCC", parent=base["Normal"],
                                 fontSize=6.5, fontName="Helvetica", textColor=TEXT_DARK,
                                 alignment=TA_CENTER, leading=9)

    return s


# ---------------------------------------------------------------------------
# Base table style
# ---------------------------------------------------------------------------

def _base_tbl_style(has_footer: bool = False) -> list:
    cmds = [
        ("BACKGROUND",    (0, 0),  (-1, 0),  LIGHT_GREEN),
        ("GRID",          (0, 0),  (-1, -1), 0.4, TABLE_GRID),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("FONTSIZE",      (0, 0),  (-1, -1), 7.5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if has_footer else -1),
         [colors.white, LIGHT_BG]),
    ]
    if has_footer:
        cmds += [
            ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE",  (0, -1), (-1, -1), 1, GQM_GREEN),
            ("BACKGROUND", (0, -1), (-1, -1), LIGHT_GREEN),
        ]
    return cmds


# ---------------------------------------------------------------------------
# Charts  — legend inside/near chart, high DPI
# ---------------------------------------------------------------------------

def _chart_monthly(monthly: list[dict], pct_label: str) -> bytes | None:
    if not monthly:
        return None

    months = [m["month"] for m in monthly]
    quoted = [m["quoted"] for m in monthly]
    sold = [m["final_sold"] for m in monthly]
    margins = [m["avg_final_pct"] for m in monthly]

    n = len(months)
    fig, ax1 = plt.subplots(figsize=(7.4, 3.4))
    x = range(n)
    w = 0.35

    b1 = ax1.bar([i - w/2 for i in x], quoted, w, label="Total Quoted",
                 color=MPL_BORDER, edgecolor="#B0BEB8", alpha=0.85)
    b2 = ax1.bar([i + w/2 for i in x], sold, w, label="Final Sold",
                 color=MPL_GREEN, alpha=0.9)

    ax1.set_ylabel("Financial Amount ($)", fontsize=8,
                   fontweight="bold", color=MPL_GREEN)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(_y_fmt))
    ax1.tick_params(axis="y", labelsize=7, labelcolor=MPL_GREEN)
    ax1.spines["top"].set_visible(False)

    ax2 = ax1.twinx()
    l1, = ax2.plot(list(x), margins, color=MPL_ORANGE, marker="o",
                   linewidth=2, markersize=5, label=pct_label)
    ax2.set_ylabel(pct_label, color=MPL_ORANGE,
                   fontsize=8, fontweight="bold")
    max_m = max(margins) if margins else 1.0
    ax2.set_ylim(0, max(max_m * 1.2, 1.05))
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    ax2.tick_params(axis="y", labelsize=7, labelcolor=MPL_ORANGE)

    rotation = 45 if n > 6 else 0
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(months, fontsize=6.5,
                        rotation=rotation, ha="right" if rotation else "center")

    # Legend inside top area — no wasted whitespace below
    handles = [b1, b2, l1]
    labels = ["Total Quoted", "Final Sold", pct_label]
    ax1.legend(handles, labels, loc='upper center', fontsize=7,
               frameon=False, ncol=3, bbox_to_anchor=(0.5, 1.15))

    fig.tight_layout(pad=0.5)
    return _save_chart(fig)


def _chart_quarterly(quarterly: list[dict], pct_label: str) -> bytes | None:
    if not quarterly:
        return None

    qtrs = [q["quarter"] for q in quarterly]
    quoted = [q["quoted"] for q in quarterly]
    sold = [q["final_sold"] for q in quarterly]
    pcts = [q["avg_final_pct"] for q in quarterly]

    fig, ax1 = plt.subplots(figsize=(5.5, 3.0))
    x = range(len(qtrs))
    w = 0.32 if len(x) > 1 else 0.15

    b1 = ax1.bar([i - w/2 for i in x], quoted, w, label="Quoted",
                 color=MPL_BORDER, edgecolor="#B0BEB8", alpha=0.85)
    b2 = ax1.bar([i + w/2 for i in x], sold,   w, label="Final Sold",
                 color=MPL_GREEN, alpha=0.9)

    if len(x) == 1:
        ax1.set_xlim(-1, 1)

    ax1.yaxis.set_major_formatter(plt.FuncFormatter(_y_fmt))
    ax1.tick_params(axis="y", labelsize=7, labelcolor=MPL_GREEN)
    ax1.set_ylabel("Amount ($)", fontsize=8,
                   color=MPL_GREEN, fontweight="bold")
    ax1.spines["top"].set_visible(False)

    rotation = 45 if len(x) > 6 else 0
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(qtrs, fontsize=6.5,
                        rotation=rotation, ha="right" if rotation else "center")

    ax2 = ax1.twinx()
    l1, = ax2.plot(list(x), pcts, color=MPL_ORANGE, marker="o",
                   linewidth=2, markersize=5, label=pct_label)
    max_p = max(pcts) if pcts else 1.0
    ax2.set_ylim(0, max(max_p * 1.2, 1.05))
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    ax2.tick_params(axis="y", labelsize=7, labelcolor=MPL_ORANGE)
    ax2.set_ylabel(pct_label, fontsize=8, color=MPL_ORANGE, fontweight="bold")

    handles = [b1, b2, l1]
    labels = ["Quoted", "Final Sold", pct_label]
    ax1.legend(handles, labels, loc='upper center', fontsize=7,
               frameon=False, ncol=3, bbox_to_anchor=(0.5, 1.15))

    fig.tight_layout(pad=0.5)
    return _save_chart(fig)


def _chart_rep(rep_list: list[dict], rep_label: str, pct_label: str) -> bytes | None:
    if not rep_list:
        return None

    reps = [r["rep"] for r in rep_list]
    finals = [r["final"] for r in rep_list]
    pcts = [r["avg_final_pct"] for r in rep_list]

    max_p = max(pcts) if pcts else 1
    norm_pcts = [p / max_p for p in pcts]
    cmap = plt.get_cmap("YlGn")
    bar_colors = [cmap(0.35 + 0.55 * p) for p in norm_pcts]

    fig_h = max(2.5, len(reps) * 0.42)
    fig, ax = plt.subplots(figsize=(6.5, fig_h))
    y = range(len(reps))

    bars = ax.barh(list(y), finals, color=bar_colors,
                   edgecolor="#ccc", linewidth=0.4, height=0.55)

    x_max = max(finals) if finals else 1
    for bar, val, pct in zip(bars, finals, pcts):
        ax.text(bar.get_width() + x_max * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{_fmt_money(val)}  ({(pct * 100):.1f}%)",
                va="center", ha="left", fontsize=6.5, color=MPL_GREEN)

    ax.set_yticks(list(y))
    ax.set_yticklabels(reps, fontsize=8)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(_y_fmt))
    ax.tick_params(axis="x", labelsize=7)
    ax.set_xlabel("Total Final Sold", fontsize=8,
                  color=MPL_GREEN, fontweight="bold")
    ax.set_title(f"{rep_label} Performance — Total Final Sold & {pct_label}",
                 fontsize=9, fontweight="bold", color=MPL_GREEN, pad=8)
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(right=x_max * 1.35)

    fig.tight_layout(pad=0.5)
    return _save_chart(fig)


def _chart_status(status_list: list[dict]) -> bytes | None:
    if not status_list:
        return None

    labels = [s["status"] for s in status_list]
    counts = [s["count"] for s in status_list]
    bg_map = {
        # --- COMUNES / QID ---
        "Assigned/P.quote":             "#D1F3EC",
        "Waiting for approval":         "#2564EBB1",
        "Scheduled/Work in progress":   "#EFEF94",
        "Cancelled":                    "#F68F8F",
        "Completed P.INV / POs":        "#7C3AED",
        "Invoiced":                     "#FF8B38",
        "HOLD":                         "#F7F0C5",
        "PAID":                         "#7BEB7C",
        "Warranty":                     "#B5E3FF",

        # --- ESPECÍFICOS PTL ---
        "Received-Stand By":            "#FFCD82",
        "Assigned-In progress":         "#EFEF94",
        "Completed PVI":                "#7C3AEDCA",
        "Paid":                         "#7BEB7DC7",

        # --- ESPECÍFICOS PAR ---
        "In Progress":                  "#F7F784",
    }
    bar_colors = [bg_map.get(l, "#6B7280") for l in labels]

    fig, ax = plt.subplots(figsize=(8.5, 3.5))
    bars = ax.bar(range(len(labels)), counts, color=bar_colors,
                  edgecolor="#D8D8D8", linewidth=0.6, width=0.55)

    top = max(counts) if counts else 1
    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + top * 0.02,
                str(cnt), ha="center", va="bottom", fontsize=6,
                fontweight="bold", color=MPL_GREEN)

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=7.5, rotation=15, ha="right")
    ax.set_ylabel("# Jobs", fontsize=8, color=MPL_GREEN, fontweight="bold")
    ax.tick_params(axis="y", labelsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(top=top * 1.20)

    fig.tight_layout(pad=0.5)
    return _save_chart(fig)


def _chart_service(service_list: list[dict]) -> bytes | None:
    if not service_list:
        return None

    items = service_list[:10]
    services = [s["service"] for s in items]
    finals = [s["final"] for s in items]
    premiums = [s["premium"] for s in items]

    fig_h = max(2.8, len(services) * 0.4)
    fig, ax = plt.subplots(figsize=(6.5, fig_h))
    y = range(len(services))
    h = 0.35

    ax.barh([i + h/2 for i in y], finals,   h,
            label="Final Sold", color=MPL_GREEN,  alpha=0.88)
    ax.barh([i - h/2 for i in y], premiums, h,
            label="Premium $",  color=MPL_ORANGE, alpha=0.88)

    ax.set_yticks(list(y))
    ax.set_yticklabels(services, fontsize=7.5)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(_y_fmt))
    ax.tick_params(axis="x", labelsize=7)
    ax.set_xlabel("Amount ($)", fontsize=8, fontweight="bold", color=MPL_GREEN)
    ax.set_title("Service Type Profitability",
                 fontsize=9, fontweight="bold", color=MPL_GREEN, pad=8)
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Legend inside lower-right where bars are shortest
    ax.legend(loc="lower right", fontsize=7, framealpha=0.8)

    fig.tight_layout(pad=0.5)
    return _save_chart(fig)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _build_header(logo_path: str | None, filters: dict, styles: dict) -> list:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    f_year = filters.get("year") or "ALL"
    f_month = filters.get("month") or "ALL"
    f_type = filters.get("job_type") or "ALL"
    f_rep = filters.get("rep") or "ALL"
    f_client = filters.get("client_id") or "ALL"

    meta = (f"Period: {f_year} / {f_month}  •  Job Type: {f_type}  •  "
            f"Rep: {f_rep}  •  Client: {f_client}  •  Generated: {generated}")

    logo_cell: object = Paragraph("<b>GQM</b>", styles["MainTitle"])
    if logo_path:
        p = Path(logo_path)
        if p.exists():
            logo_cell = _fit_logo(
                str(p.absolute()), max_w=0.8*inch, max_h=0.4*inch)

    title_cell = [
        Paragraph("Jobs Financial Performance Report", styles["MainTitle"]),
        Paragraph(meta, styles["SubTitle"]),
    ]

    tbl = Table([[logo_cell, title_cell]],
                colWidths=[1.5*inch, PAGE_W - 1.5*inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))

    return [
        tbl,
        HRFlowable(width="100%", thickness=2, color=GQM_GREEN, spaceAfter=10),
        Spacer(1, 2),
    ]


# ---------------------------------------------------------------------------
# KPI Cards
# ---------------------------------------------------------------------------

def _build_kpi_cards(summary: dict, pipeline: float, styles: dict, pct_label: str) -> list:
    def card(label, value, sub=""):
        return [
            Spacer(1, 6),
            Paragraph(label, styles["CardLabel"]),
            Spacer(1, 3),
            Paragraph(value, styles["CardVal"]),
            Spacer(1, 2),
            Paragraph(sub, styles["CardSub"]),
            Spacer(1, 6),
        ]

    paid = summary.get("paid_count", 0)
    total = summary.get("job_count",  0)

    row1 = [
        card("TOTAL QUOTED",      _fmt_money(summary.get(
            "total_quoted")),     "Target Sold Pricing"),
        card("TOTAL FORMULA",     _fmt_money(
            summary.get("total_formula")),    "Base Costing"),
        card("TOTAL FINAL SOLD",  _fmt_money(
            summary.get("total_final_sold")), "Actual Revenue"),
        card("TOTAL PREMIUM $",   _fmt_money(summary.get(
            "total_premium")),    "Final Sold − Adj Formula"),
    ]
    row2 = [
        card(pct_label.upper(),       _fmt_pct(summary.get(
            "avg_final_pct")),      "Margin Performance"),
        card("# JOBS PAID",       str(paid),
             f"of {total} total jobs"),
        card("PIPELINE",          _fmt_money(pipeline),
             "Active / Uncollected"),
        card("AVG TARGET RETURN", _fmt_pct(summary.get(
            "avg_target_ret")),     "Strategic Objective"),
    ]

    tbl = Table([row1, row2], colWidths=[PAGE_W / 4] * 4)
    tbl.setStyle(TableStyle([
        ("GRID",       (0, 0), (-1, -1), 0.5, CARD_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("BOX",        (0, 0), (-1, -1), 1,   GQM_GREEN),
    ]))
    return [
        Paragraph("Executive Summary", styles["SectionHeader"]),
        tbl,
        Spacer(1, 10),
    ]


# ---------------------------------------------------------------------------
# Monthly
# ---------------------------------------------------------------------------

def _build_monthly_section(monthly: list[dict], styles: dict, pct_label: str) -> list:
    if not monthly:
        return []

    story = [Paragraph("Monthly Financial Evolution", styles["SectionHeader"])]

    chart_png = _chart_monthly(monthly, pct_label)
    if chart_png:
        story.append(Image(io.BytesIO(chart_png),
                     width=PAGE_W, height=3.3*inch))
        story.append(Spacer(1, 8))   # tight gap between chart and table

    hdr = [Paragraph(h, styles["THeader"]) for h in
           ["Month", "Jobs", "Paid", "Quoted", "Formula", "Adj Formula",
            "Final Sold", "Premium $", pct_label]]
    rows = [hdr]
    for m in monthly:
        rows.append([
            Paragraph(m["month"],                   styles["TCellB"]),
            Paragraph(str(m["jobs"]),               styles["TCellC"]),
            Paragraph(str(m["paid_jobs"]),          styles["TCellC"]),
            Paragraph(_fmt_money(m["quoted"]),      styles["TCellR"]),
            Paragraph(_fmt_money(m["formula"]),     styles["TCellR"]),
            Paragraph(_fmt_money(m["adj_formula"]), styles["TCellR"]),
            Paragraph(_fmt_money(m["final_sold"]),  styles["TCellR"]),
            Paragraph(_fmt_money(m["premium"]),     styles["TCellR"]),
            Paragraph(_fmt_pct(m["avg_final_pct"]), styles["TCellR"]),
        ])
    rows.append([
        Paragraph("TOTAL",
                  styles["TCellB"]),
        Paragraph(str(sum(m["jobs"] for m in monthly)),
                  styles["TCellC"]),
        Paragraph(str(sum(m["paid_jobs"]
                  for m in monthly)),           styles["TCellC"]),
        Paragraph(_fmt_money(sum(m["quoted"]
                  for m in monthly)),    styles["TCellRB"]),
        Paragraph(_fmt_money(sum(m["formula"]
                  for m in monthly)),    styles["TCellRB"]),
        Paragraph(_fmt_money(sum(m["adj_formula"]
                  for m in monthly)),    styles["TCellRB"]),
        Paragraph(_fmt_money(sum(m["final_sold"]
                  for m in monthly)),    styles["TCellRB"]),
        Paragraph(_fmt_money(sum(m["premium"]
                  for m in monthly)),    styles["TCellRB"]),
        Paragraph("",
                  styles["TCell"]),
    ])

    col_w = [0.80*inch, 0.50*inch, 0.50*inch, 0.90*inch, 0.90*inch,
             0.90*inch, 0.90*inch, 0.90*inch, 0.80*inch]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_tbl_style(has_footer=True)))
    story.append(tbl)
    return [
        KeepTogether(story),
        Spacer(1, 10)
    ]


# ---------------------------------------------------------------------------
# Quarterly
# ---------------------------------------------------------------------------

def _build_quarterly_section(quarterly: list[dict], styles: dict, pct_label: str) -> list:
    if not quarterly:
        return []

    story = [Paragraph("Quarterly Breakdown", styles["SectionHeader"])]

    chart_png = _chart_quarterly(quarterly, pct_label)
    if chart_png:
        story.append(Image(io.BytesIO(chart_png),
                     width=5.5*inch, height=2.9*inch))
        story.append(Spacer(1, 8))

    hdr = [Paragraph(h, styles["THeader"]) for h in
           ["Quarter", "Jobs", "Paid", "Quoted", "Formula",
            "Final Sold", "Premium $", pct_label]]
    rows = [hdr]
    for q in quarterly:
        rows.append([
            Paragraph(q["quarter"],                styles["TCellB"]),
            Paragraph(str(q["jobs"]),              styles["TCellC"]),
            Paragraph(str(q["paid_jobs"]),         styles["TCellC"]),
            Paragraph(_fmt_money(q["quoted"]),     styles["TCellR"]),
            Paragraph(_fmt_money(q["formula"]),    styles["TCellR"]),
            Paragraph(_fmt_money(q["final_sold"]), styles["TCellR"]),
            Paragraph(_fmt_money(q["premium"]),    styles["TCellR"]),
            Paragraph(_fmt_pct(q["avg_final_pct"]), styles["TCellR"]),
        ])
    rows.append([
        Paragraph("TOTAL",
                  styles["TCellB"]),
        Paragraph(str(sum(q["jobs"] for q in quarterly)),
                  styles["TCellC"]),
        Paragraph(str(sum(q["paid_jobs"]
                  for q in quarterly)),          styles["TCellC"]),
        Paragraph(_fmt_money(sum(q["quoted"]
                  for q in quarterly)),   styles["TCellRB"]),
        Paragraph(_fmt_money(sum(q["formula"]
                  for q in quarterly)),   styles["TCellRB"]),
        Paragraph(_fmt_money(sum(q["final_sold"]
                  for q in quarterly)),   styles["TCellRB"]),
        Paragraph(_fmt_money(sum(q["premium"]
                  for q in quarterly)),   styles["TCellRB"]),
        Paragraph("",
                  styles["TCell"]),
    ])

    col_w = [0.85*inch, 0.55*inch, 0.55*inch, 1.05*inch,
             1.05*inch, 1.05*inch, 1.05*inch, 1.00*inch]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_tbl_style(has_footer=True)))
    story.append(tbl)
    return [
        KeepTogether(story),
        Spacer(1, 10)
    ]


# ---------------------------------------------------------------------------
# Rep
# ---------------------------------------------------------------------------

def _build_rep_section(rep_list: list[dict], rep_label: str, pct_label: str, styles: dict) -> list:
    if not rep_list:
        return []

    story = [Paragraph(f"{rep_label} Performance", styles["SectionHeader"])]

    chart_png = _chart_rep(rep_list, rep_label, pct_label)
    if chart_png:
        chart_h = max(2.5, len(rep_list) * 0.42)
        story.append(Image(io.BytesIO(chart_png),
                     width=6.5*inch, height=chart_h*inch))
        story.append(Spacer(1, 8))

    hdr = [Paragraph(h, styles["THeader"]) for h in
           [rep_label, "Jobs", "Paid", "Total Quoted",
            "Total Final Sold", pct_label, "Total Premium $"]]
    rows = [hdr]
    for r in rep_list:
        rows.append([
            Paragraph(r["rep"],                    styles["TCellB"]),
            Paragraph(str(r["jobs"]),              styles["TCellC"]),
            Paragraph(str(r["paid"]),              styles["TCellC"]),
            Paragraph(_fmt_money(r["quoted"]),     styles["TCellR"]),
            Paragraph(_fmt_money(r["final"]),      styles["TCellR"]),
            Paragraph(_fmt_pct(r["avg_final_pct"]), styles["TCellR"]),
            Paragraph(_fmt_money(r["premium"]),    styles["TCellR"]),
        ])

    col_w = [1.60*inch, 0.50*inch, 0.50*inch, 1.10*inch,
             1.10*inch, 0.90*inch, 1.10*inch]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_tbl_style()))
    story.append(tbl)
    return [
        KeepTogether(story),
        Spacer(1, 10)
    ]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _build_status_section(status_list: list[dict], pipeline: float, styles: dict) -> list:
    if not status_list:
        return []

    story = [Paragraph("Job Status Distribution & Pipeline",
                       styles["SectionHeader"])]
    story.append(Paragraph(
        f"Pipeline indicator (active jobs — Pending, Partial, In Progress, Overdue): "
        f"<b>{_fmt_money(pipeline)}</b>",
        styles["Muted"]))
    story.append(Spacer(1, 6))

    chart_png = _chart_status(status_list)
    if chart_png:
        story.append(Image(io.BytesIO(chart_png),
                     width=5.5*inch, height=2.7*inch))
        story.append(Spacer(1, 8))

    hdr = [Paragraph(h, styles["THeader"]) for h in
           ["Status", "# Jobs", "% Total", "Total Quoted",
            "Total Final Sold", "Total Premium $"]]
    rows = [hdr]
    row_cmds = []
    for i, s in enumerate(status_list, start=1):
        sn = s["status"]
        rows.append([
            Paragraph(sn, styles["TCellB"]),
            Paragraph(str(s["count"]),         styles["TCellC"]),
            Paragraph(_fmt_pct(s["pct"]),      styles["TCellC"]),
            Paragraph(_fmt_money(s["quoted"]), styles["TCellR"]),
            Paragraph(_fmt_money(s["final"]),  styles["TCellR"]),
            Paragraph(_fmt_money(s["premium"]), styles["TCellR"]),
        ])

    col_w = [1.5*inch, 0.65*inch, 0.65*inch, 1.35*inch, 1.35*inch, 1.35*inch]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_tbl_style() + row_cmds))
    story.append(tbl)
    return [
        KeepTogether(story),
        Spacer(1, 10)
    ]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _build_service_section(service_list: list[dict], styles: dict) -> list:
    if not service_list:
        return []

    story = []

    story.append(Paragraph("Profitability by Service Type",
                 styles["SectionHeader"]))

    chart_png = _chart_service(service_list)
    if chart_png:
        chart_h = max(2.5, min(len(service_list), 10) * 0.42)
        story.append(Image(io.BytesIO(chart_png),
                     width=6.5*inch, height=chart_h*inch))
        story.append(Spacer(1, 8))

    hdr = [Paragraph(h, styles["THeader"]) for h in
           ["Service Category", "# Jobs", "Avg Final %",
            "Total Final Sold", "Total Premium $"]]
    rows = [hdr]
    for s in service_list:
        rows.append([
            Paragraph(s["service"],                  styles["TCellB"]),
            Paragraph(str(s["count"]),               styles["TCellC"]),
            Paragraph(_fmt_pct(s["avg_final_pct"]),  styles["TCellC"]),
            Paragraph(_fmt_money(s["final"]),         styles["TCellR"]),
            Paragraph(_fmt_money(s["premium"]),       styles["TCellR"]),
        ])

    col_w = [2.20*inch, 0.70*inch, 1.00*inch, 1.55*inch, 1.55*inch]
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_tbl_style()))
    story.append(tbl)
    return [
        KeepTogether(story),
        Spacer(1, 15)
    ]


# ---------------------------------------------------------------------------
# Job detail table
# ---------------------------------------------------------------------------

def _job_detail_chunk(chunk: list[dict], job_type: str, rep_label: str, pct_label: str, styles: dict) -> Table:
    hide_service = job_type in ("PTL", "PAR")
    hide_final = job_type == "PAR"

    hdr_labels = ["Job ID", "Client", rep_label, "Status"]
    if not hide_service:
        hdr_labels.append("Service")
    hdr_labels.extend(["Date", "Formula Cost", "Adj Formula Cost", "Target Sold"])
    if not hide_final:
        hdr_labels.append("Final Sold")
    hdr_labels.extend([pct_label, "Premium $"])

    if not hide_service and not hide_final: # QID, ALL
        col_w = [0.60*inch, 0.85*inch, 0.70*inch, 0.70*inch, 0.60*inch,
                 0.60*inch, 0.65*inch, 0.65*inch, 0.65*inch, 0.65*inch,
                 0.45*inch, 0.60*inch]
    elif hide_service and not hide_final: # PTL
        col_w = [0.65*inch, 1.05*inch, 0.85*inch, 0.70*inch, 0.70*inch,
                 0.70*inch, 0.70*inch, 0.65*inch, 0.65*inch, 0.50*inch,
                 0.55*inch]
    else: # PAR
        col_w = [0.70*inch, 1.10*inch, 0.90*inch, 0.80*inch, 0.80*inch,
                 0.70*inch, 0.70*inch, 0.70*inch, 0.60*inch, 0.70*inch]

    hdr = [Paragraph(h, styles["THeader"]) for h in hdr_labels]
    rows = [hdr]
    row_cmds = []

    for i, j in enumerate(chunk, start=1):
        status = j["status"] or ""

        client = j["client"]
        if len(client) > 22:
            client = client[:19] + "…"

        row_data = [
            Paragraph(j["job_id"],                 styles["TCellB"]),
            Paragraph(client,                       styles["TCell"]),
            Paragraph(j["rep"],                    styles["TCell"]),
            Paragraph(f'<b>{status}</b>',          styles["TCellC"]),
        ]
        
        if not hide_service:
            row_data.append(Paragraph(j["service"], styles["TCell"]))

        row_data.extend([
            Paragraph(j["date"],                   styles["TCellC"]),
            Paragraph(_fmt_money(j["formula"]),    styles["TCellR"]),
            Paragraph(_fmt_money(j["adj_formula"]), styles["TCellR"]),
            Paragraph(_fmt_money(j["target"]),     styles["TCellR"]),
        ])
        
        if not hide_final:
            row_data.append(Paragraph(_fmt_money(j["final"]), styles["TCellR"]))
            
        row_data.extend([
            Paragraph(_fmt_pct(j["pct"]),          styles["TCellR"]),
            Paragraph(_fmt_money(j["premium"]),    styles["TCellR"]),
        ])
        rows.append(row_data)

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  LIGHT_GREEN),
        ("GRID",          (0, 0),  (-1, -1), 0.3, TABLE_GRID),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("FONTSIZE",      (0, 0),  (-1, -1), 6.8),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 4),
        ("TOPPADDING",    (0, 0),  (-1, -1), 4),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1),  (-1, -1), [colors.white, LIGHT_BG]),
    ] + row_cmds))
    return tbl


def _build_job_detail_section(jobs: list[dict], job_type: str, rep_label: str, pct_label: str, styles: dict) -> list:
    if not jobs:
        return []

    story = [
        PageBreak(),
        Paragraph("Job Record Detail — Full Inventory Log",
                  styles["SectionHeader"]),
        Paragraph(f"{len(jobs)} jobs — sorted by Overdue first, then by date assigned.",
                  styles["Muted"]),
        Spacer(1, 4),
    ]

    story.append(_job_detail_chunk(jobs, job_type, rep_label, pct_label, styles))
    story.append(Spacer(1, 6))

    return story


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_job_financial_report(
    data: dict,
    *,
    company_name: str = "Company",
    logo_path: str | None = None,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.40*inch, rightMargin=0.40*inch,
        topMargin=0.40*inch,  bottomMargin=0.45*inch,
        title="Jobs Financial Performance Report",
        author=company_name,
    )

    styles = _make_styles()
    filters = data.get("filters", {})
    summary = data.get("summary", {})
    job_type = filters.get("job_type") or "ALL"
    rep_label = data.get("rep_label", "Rep")
    pct_label = data.get("pct_label", "Avg Final %")
    pipeline = float(data.get("pipeline", 0))
    story = []

    story.extend(_build_header(logo_path, filters, styles))
    story.extend(_build_kpi_cards(summary, pipeline, styles, pct_label))
    story.extend(_build_monthly_section(data.get("monthly",   []), styles, pct_label))
    story.extend(_build_quarterly_section(data.get("quarterly", []), styles, pct_label))
    story.extend(_build_rep_section(data.get("rep",       []), rep_label, pct_label, styles))
    story.extend(_build_status_section(
        data.get("status",    []), pipeline, styles))
    story.extend(_build_service_section(data.get("service",   []), styles))
    story.extend(_build_job_detail_section(data.get("jobs",      []), job_type, rep_label, pct_label, styles))

    def _on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawRightString(8.1*inch, 0.28*inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
