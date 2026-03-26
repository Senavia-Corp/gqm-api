from __future__ import annotations
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import LETTER
import matplotlib.pyplot as plt

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")


# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------
GQM_GREEN = colors.HexColor("#0B2E1E")
GQM_ORANGE = colors.HexColor("#F28C00")
LIGHT_BG = colors.HexColor("#F6F7F8")
CARD_BORDER = colors.HexColor("#D9E1DD")
TABLE_HEADER = colors.HexColor("#EDF3F0")
TABLE_GRID = colors.HexColor("#DCE6E1")
TEXT_MUTED = colors.HexColor("#5B6B63")
EMERALD = colors.HexColor("#059669")
ORANGE_ACC = colors.HexColor("#EA580C")   # kept for internal use
TEAL_ACC = colors.HexColor("#0D7377")   # Invoices
CORAL_ACC = colors.HexColor("#C2410C")   # Bills
BLUE_ACC = colors.HexColor("#2563EB")
PURPLE_ACC = colors.HexColor("#7C3AED")
RED_ACC = colors.HexColor("#DC2626")
AMBER_ACC = colors.HexColor("#D97706")
GREEN_LIGHT = colors.HexColor("#D1FAE5")
RED_LIGHT = colors.HexColor("#FEE2E2")
AMBER_LIGHT = colors.HexColor("#FEF3C7")
BLUE_LIGHT = colors.HexColor("#DBEAFE")
GRAY_LIGHT = colors.HexColor("#F3F4F6")

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

STATUS_COLORS = {
    "Paid":    EMERALD,
    "Partial": AMBER_ACC,
    "Pending": BLUE_ACC,
    "Overdue": RED_ACC,
    "Voided":  TEXT_MUTED,
}
STATUS_BG_COLORS = {
    "Paid":    GREEN_LIGHT,
    "Partial": AMBER_LIGHT,
    "Pending": BLUE_LIGHT,
    "Overdue": RED_LIGHT,
    "Voided":  GRAY_LIGHT,
}
JOB_STATUS_COLORS = {
    "Settled": EMERALD,
    "Partial": AMBER_ACC,
    "Overdue": RED_ACC,
}

# Usable page width: 8.5in - 2*0.55in margins
PAGE_W = 7.4 * inch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_money(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def _fit_logo(path: str, max_w: float, max_h: float) -> Image:
    img = ImageReader(path)
    iw, ih = img.getSize()
    scale = min(max_w / float(iw), max_h / float(ih))
    return Image(path, width=iw * scale, height=ih * scale)


# ---------------------------------------------------------------------------
# Style factory
# ---------------------------------------------------------------------------

def _make_styles():
    base = getSampleStyleSheet()

    styles = {}
    styles["H1"] = ParagraphStyle("FH1", parent=base["Title"],
                                  fontName="Helvetica-Bold", fontSize=17, leading=20,
                                  textColor=colors.white, alignment=1, spaceAfter=2)

    styles["SmallWhite"] = ParagraphStyle("FSmallWhite", parent=base["Normal"],
                                          fontName="Helvetica", fontSize=7.5, leading=10,
                                          textColor=colors.white, alignment=2)

    styles["SectionTitle"] = ParagraphStyle("FSectionTitle", parent=base["Heading2"],
                                            fontName="Helvetica-Bold", fontSize=11, leading=13,
                                            textColor=GQM_GREEN, spaceBefore=10, spaceAfter=5)

    styles["Muted"] = ParagraphStyle("FMuted", parent=base["Normal"],
                                     fontName="Helvetica", fontSize=8, leading=10,
                                     textColor=TEXT_MUTED, spaceAfter=4)

    styles["CardLabel"] = ParagraphStyle("FCardLabel", parent=base["Normal"],
                                         fontName="Helvetica-Bold", fontSize=8, leading=10,
                                         textColor=GQM_GREEN, spaceAfter=2)

    styles["CardValue"] = ParagraphStyle("FCardValue", parent=base["Normal"],
                                         fontName="Helvetica-Bold", fontSize=14, leading=16,
                                         textColor=colors.black, spaceAfter=0)

    styles["CardSub"] = ParagraphStyle("FCardSub", parent=base["Normal"],
                                       fontName="Helvetica", fontSize=7, leading=9,
                                       textColor=TEXT_MUTED, spaceAfter=0)

    # Table cell styles
    styles["Cell"] = ParagraphStyle("FCell", parent=base["Normal"],
                                    fontName="Helvetica", fontSize=7.5, leading=9, textColor=colors.black)
    styles["CellHdr"] = ParagraphStyle("FCellHdr", parent=base["Normal"],
                                       fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=GQM_GREEN)
    styles["CellR"] = ParagraphStyle("FCellR", parent=base["Normal"],
                                     fontName="Helvetica", fontSize=7.5, leading=9, textColor=colors.black, alignment=2)
    styles["CellRB"] = ParagraphStyle("FCellRB", parent=base["Normal"],
                                      fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.black, alignment=2)
    styles["CellB"] = ParagraphStyle("FCellB", parent=base["Normal"],
                                     fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.black)
    styles["CellC"] = ParagraphStyle("FCellC", parent=base["Normal"],
                                     fontName="Helvetica", fontSize=7.5, leading=9, textColor=colors.black, alignment=1)

    return styles


# ---------------------------------------------------------------------------
# Shared base table style
# ---------------------------------------------------------------------------

def _base_table_style() -> list:
    return [
        ("BACKGROUND",    (0, 0),  (-1, 0),  TABLE_HEADER),
        ("GRID",          (0, 0),  (-1, -1), 0.4, TABLE_GRID),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("FONTSIZE",      (0, 0),  (-1, -1), 7.5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1),  (-1, -2), [colors.white, LIGHT_BG]),
        ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE",     (0, -1), (-1, -1), 1, GQM_GREEN),
        ("BACKGROUND",    (0, -1), (-1, -1), TABLE_HEADER),
    ]


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _make_bar_chart_png(monthly: list[dict]) -> bytes:
    if not monthly:
        fig, ax = plt.subplots(figsize=(7, 3), dpi=150)
        ax.text(0.5, 0.5, "No monthly data available",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    n = len(monthly)
    labels = [r["month_name"][:3] for r in monthly]
    inv_total = [r["invoices_total"] for r in monthly]
    inv_coll = [r["invoices_collected"] for r in monthly]
    bill_tot = [r["bills_total"] for r in monthly]
    bill_paid = [r["bills_paid"] for r in monthly]
    net_flow = [r["net_flow"] for r in monthly]

    x = range(n)
    # Narrow bars when many months to avoid overlap
    w = max(0.10, min(0.18, 0.9 / (n + 1)))
    # Wider figure when many months
    fig_w = max(7.2, min(n * 0.55, 14.0))

    fig, ax = plt.subplots(figsize=(fig_w, 3.8), dpi=160)
    ax.bar([i - 1.5*w for i in x], inv_total, w,
           label="Invoiced",  color="#0D7377", alpha=0.90)
    ax.bar([i - 0.5*w for i in x], inv_coll,  w,
           label="Collected", color="#0D7377", alpha=0.55)
    ax.bar([i + 0.5*w for i in x], bill_tot,  w,
           label="Billed",    color="#C2410C", alpha=0.90)
    ax.bar([i + 1.5*w for i in x], bill_paid, w,
           label="Paid",      color="#C2410C", alpha=0.55)
    ax.plot(list(x), net_flow, color="#2563EB", linewidth=1.5,
            marker="o", markersize=3, label="Net Flow", zorder=5)

    ax.set_xticks(list(x))
    # Rotate labels when many months to prevent overlap
    rotation = 45 if n > 6 else 0
    ax.set_xticklabels(labels, fontsize=7, rotation=rotation,
                       ha="right" if rotation else "center")

    def _fmt_y(v, _):
        if abs(v) >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if abs(v) >= 1000:
            return f"${v/1000:.0f}k"
        return f"${v:.0f}"

    ax.yaxis.set_major_formatter(plt.FuncFormatter(_fmt_y))
    ax.tick_params(axis="y", labelsize=7)
    ax.axhline(0, color="#ccc", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title("Monthly Financial Overview",
                 fontsize=10, fontweight="bold", pad=10)

    ymax = max(max(inv_total or [0]), max(bill_tot or [0]))
    ymin = min(min(net_flow or [0]), 0)
    ax.set_ylim(
        bottom=ymin * 1.25 if ymin < 0 else -ymax * 0.05,
        top=ymax * 1.25,
    )

    # Legend below the chart — avoids overlap with title and tallest bars
    ax.legend(fontsize=7, frameon=False, ncol=5,
              loc="upper center", bbox_to_anchor=(0.5, -0.20))
    fig.tight_layout(rect=[0, 0.10, 1, 1])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _make_donut_png(inv_total: float, bill_total: float) -> bytes:
    if inv_total == 0 and bill_total == 0:
        inv_total = bill_total = 1
    total = inv_total + bill_total

    fig = plt.figure(figsize=(4.0, 2.6), dpi=160)
    ax = fig.add_subplot(111)
    wedges, _ = ax.pie(
        [inv_total, bill_total], startangle=90,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1},
        colors=["#0D7377", "#C2410C"],
    )
    ax.axis("equal")
    ax.legend(wedges,
              [f"Invoices ({inv_total/total*100:.1f}%)",
               f"Bills ({bill_total/total*100:.1f}%)"],
              loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=8)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _make_aging_chart_png(aging: dict) -> bytes:
    rows = aging.get("rows", [])
    if not rows:
        fig, ax = plt.subplots(figsize=(6, 2), dpi=150)
        ax.text(0.5, 0.5, "No outstanding balances",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    buckets = [r["bucket"] for r in rows]
    inv_vals = [r["inv_balance"] for r in rows]
    bill_vals = [r["bill_balance"] for r in rows]
    y = range(len(buckets))
    h = 0.35

    fig, ax = plt.subplots(
        figsize=(6.0, max(2.0, len(buckets) * 0.6 + 0.8)), dpi=160)
    ax.barh([i + h/2 for i in y], inv_vals,  h,
            label="Invoices", color="#0D7377", alpha=0.90)
    ax.barh([i - h/2 for i in y], bill_vals, h,
            label="Bills",    color="#C2410C", alpha=0.90)
    ax.set_yticks(list(y))
    ax.set_yticklabels(buckets, fontsize=8)
    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"${v/1000:.0f}k" if v >= 1000 else f"${v:.0f}"))
    ax.tick_params(axis="x", labelsize=7)
    ax.legend(fontsize=7, frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title("Outstanding Balance by Aging Bucket",
                 fontsize=9, fontweight="bold", pad=6)
    ax.invert_yaxis()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _build_header(logo_path: str | None, filters: dict, styles: dict) -> Table:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    type_txt = filters.get("type") or "ALL"
    year_txt = filters.get("year") or "ALL"
    month_num = filters.get("month")
    month_txt = MONTH_NAMES[month_num] if month_num else "ALL"
    doc_txt = (filters.get("doc_type") or "all").upper()

    meta = (f"Type: {type_txt}  •  Year: {year_txt}  •  Month: {month_txt}  •  "
            f"Docs: {doc_txt}  •  Generated: {generated}")

    logo_cell: object = Paragraph("", getSampleStyleSheet()["Normal"])
    if logo_path:
        p = Path(logo_path)
        if p.exists():
            logo_cell = _fit_logo(str(p), max_w=1.55*inch, max_h=0.75*inch)

    tbl = Table(
        [[logo_cell,
          Paragraph("Financial Documents Report", styles["H1"]),
          Paragraph(meta, styles["SmallWhite"])]],
        colWidths=[1.6*inch, 3.6*inch, 2.2*inch],
        rowHeights=[0.85*inch],
    )
    tbl.setStyle(TableStyle([
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
    return tbl


# ---------------------------------------------------------------------------
# Summary cards
# ---------------------------------------------------------------------------

def _build_summary_cards(summary: dict, styles: dict) -> Table:
    def card(label, value, sub="", accent=GQM_GREEN):
        return [
            Paragraph(label, styles["CardLabel"]),
            Spacer(1, 4),
            Paragraph(
                f'<font color="{accent.hexval()}">{value}</font>', styles["CardValue"]),
            Spacer(1, 5),
            Paragraph(sub, styles["CardSub"]),
        ]

    def card_status(label, paid, partial, overdue, sub=""):
        """Card variant for status counts — styled to match other cards visually."""
        base = getSampleStyleSheet()["Normal"]
        row_style = ParagraphStyle("FCardStatusRow", parent=base,
                                   fontName="Helvetica-Bold", fontSize=9, leading=13, textColor=colors.black)
        num_style = ParagraphStyle("FCardStatusNum", parent=base,
                                   fontName="Helvetica-Bold", fontSize=13, leading=15, textColor=colors.black)
        return [
            Paragraph(label, styles["CardLabel"]),
            Spacer(1, 4),
            Paragraph(
                f'<font color="{EMERALD.hexval()}">Paid</font>'
                f'<font color="{TEXT_MUTED.hexval()}">  {paid}</font>',
                row_style),
            Paragraph(
                f'<font color="{AMBER_ACC.hexval()}">Partial</font>'
                f'<font color="{TEXT_MUTED.hexval()}">  {partial}</font>',
                row_style),
            Paragraph(
                f'<font color="{RED_ACC.hexval()}">Overdue</font>'
                f'<font color="{TEXT_MUTED.hexval()}">  {overdue}</font>',
                row_style),
            Spacer(1, 5),
            Paragraph(sub, styles["CardSub"]),
        ]

    inv_pct = _fmt_pct(summary["avg_invoice_pct_paid"])
    bill_pct = _fmt_pct(summary["avg_bill_pct_paid"])
    isc = summary["inv_status_counts"]
    bsc = summary["bill_status_counts"]
    net = summary["net_flow"]
    net_c = EMERALD if net >= 0 else RED_ACC

    row1 = [
        card("Total Invoiced",     _fmt_money(summary["total_invoiced"]),
             f'{summary["invoice_count"]} invoices  •  avg {inv_pct} paid', TEAL_ACC),
        card("Total Collected",    _fmt_money(summary["inv_collected"]),
             f'Balance: {_fmt_money(summary["inv_balance"])}', TEAL_ACC),
        card("Total Billed",       _fmt_money(summary["total_billed"]),
             f'{summary["bill_count"]} bills  •  avg {bill_pct} paid', CORAL_ACC),
        card("Total Paid (Bills)", _fmt_money(summary["bill_paid"]),
             f'Balance: {_fmt_money(summary["bill_balance"])}', CORAL_ACC),
    ]
    row2 = [
        card("Net Cash Flow",     _fmt_money(net),
             "Collected − Paid (expenses)", net_c),
        card("Total Outstanding", _fmt_money(summary["total_outstanding"]),
             f'Inv: {_fmt_money(summary["inv_balance"])}  •  Bills: {_fmt_money(summary["bill_balance"])}',
             PURPLE_ACC),
        card_status("Invoice Status",
                    isc["Paid"], isc["Partial"], isc["Overdue"],
                    f'Pending: {isc["Pending"]}  •  Voided: {isc["Voided"]}'),
        card_status("Bill Status",
                    bsc["Paid"], bsc["Partial"], bsc["Overdue"],
                    f'Pending: {bsc["Pending"]}  •  Voided: {bsc["Voided"]}'),
    ]

    tbl = Table([row1, row2], colWidths=[PAGE_W / 4] * 4)
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
    return tbl


# ---------------------------------------------------------------------------
# Monthly breakdown
# ---------------------------------------------------------------------------

def _build_monthly_section(monthly: list[dict], styles: dict) -> list:
    if not monthly:
        return [Paragraph("Monthly Breakdown", styles["SectionTitle"]),
                Paragraph("No monthly data available.", styles["Muted"])]

    S = styles
    hdr = [Paragraph(h, S["CellHdr"]) for h in
           ["Month", "Invoiced", "Collected", "Inv Bal", "Billed", "Paid", "Bill Bal", "Net Flow"]]
    data = [hdr]

    for r in monthly:
        net_c = EMERALD.hexval() if r["net_flow"] >= 0 else RED_ACC.hexval()
        data.append([
            Paragraph(r["month_name"],                    S["Cell"]),
            Paragraph(_fmt_money(r["invoices_total"]),    S["CellR"]),
            Paragraph(_fmt_money(r["invoices_collected"]), S["CellR"]),
            Paragraph(_fmt_money(r["invoices_balance"]),  S["CellR"]),
            Paragraph(_fmt_money(r["bills_total"]),       S["CellR"]),
            Paragraph(_fmt_money(r["bills_paid"]),        S["CellR"]),
            Paragraph(_fmt_money(r["bills_balance"]),     S["CellR"]),
            Paragraph(
                f'<font color="{net_c}">{_fmt_money(r["net_flow"])}</font>', S["CellR"]),
        ])

    total_net = sum(r["net_flow"] for r in monthly)
    net_c = EMERALD.hexval() if total_net >= 0 else RED_ACC.hexval()
    data.append([
        Paragraph("TOTAL",
                  S["CellB"]),
        Paragraph(_fmt_money(sum(r["invoices_total"]
                  for r in monthly)), S["CellRB"]),
        Paragraph(_fmt_money(sum(r["invoices_collected"]
                  for r in monthly)), S["CellRB"]),
        Paragraph(_fmt_money(sum(r["invoices_balance"]
                  for r in monthly)), S["CellRB"]),
        Paragraph(_fmt_money(sum(r["bills_total"]
                  for r in monthly)), S["CellRB"]),
        Paragraph(_fmt_money(sum(r["bills_paid"]
                  for r in monthly)), S["CellRB"]),
        Paragraph(_fmt_money(sum(r["bills_balance"]
                  for r in monthly)), S["CellRB"]),
        Paragraph(
            f'<font color="{net_c}">{_fmt_money(total_net)}</font>',   S["CellRB"]),
    ])

    # 8 columns summing to PAGE_W
    col_w = [0.85*inch, 0.95*inch, 0.95*inch, 0.90*inch,
             0.85*inch, 0.85*inch, 0.90*inch, 0.95*inch]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_table_style()))

    chart_png = _make_bar_chart_png(monthly)
    chart_img = Image(io.BytesIO(chart_png), width=PAGE_W, height=3.4*inch)

    return [
        Paragraph("Monthly Breakdown", styles["SectionTitle"]),
        Paragraph(
            "All amounts from document balances (Total − Balance). "
            "Net Flow = Collected − Paid (expenses).", styles["Muted"]),
        tbl,
        Spacer(1, 18),   # espacio entre tabla y gráfico
        chart_img,
        Spacer(1, 14),   # espacio después del gráfico
    ]


# ---------------------------------------------------------------------------
# Aging report
# ---------------------------------------------------------------------------

AGING_ROW_BG = {
    "Current":     LIGHT_BG,
    "1–30 days":   AMBER_LIGHT,
    "31–60 days":  AMBER_LIGHT,
    "61–90 days":  RED_LIGHT,
    "+90 days":    RED_LIGHT,
    "No Due Date": GRAY_LIGHT,
}


def _build_aging_section(aging: dict, styles: dict) -> list:
    rows = aging.get("rows", [])
    if not rows:
        return [Paragraph("Aging Report", styles["SectionTitle"]),
                Paragraph(
                    "No outstanding balances for the selected filters.", styles["Muted"]),
                Spacer(1, 6)]

    S = styles
    hdr = [Paragraph(h, S["CellHdr"]) for h in
           ["Bucket", "Inv Count", "Inv Balance", "Bill Count", "Bill Balance", "Total Outstanding"]]
    data = [hdr]
    row_bg = []

    for i, r in enumerate(rows, start=1):
        bg = AGING_ROW_BG.get(r["bucket"], colors.white)
        row_bg.append(("BACKGROUND", (0, i), (-1, i), bg))
        data.append([
            Paragraph(r["bucket"],                   S["Cell"]),
            Paragraph(str(r["inv_count"]),           S["CellC"]),
            Paragraph(_fmt_money(r["inv_balance"]),  S["CellR"]),
            Paragraph(str(r["bill_count"]),          S["CellC"]),
            Paragraph(_fmt_money(r["bill_balance"]), S["CellR"]),
            Paragraph(_fmt_money(r["total"]),        S["CellR"]),
        ])

    data.append([
        Paragraph("TOTAL OVERDUE",                        S["CellB"]),
        Paragraph("",                                     S["Cell"]),
        Paragraph(_fmt_money(aging["total_inv_overdue"]), S["CellRB"]),
        Paragraph("",                                     S["Cell"]),
        Paragraph(_fmt_money(aging["total_bill_overdue"]), S["CellRB"]),
        Paragraph(_fmt_money(aging["total_overdue"]),     S["CellRB"]),
    ])

    col_w = [1.3*inch, 0.8*inch, 1.3*inch, 0.8*inch, 1.3*inch, 1.6*inch]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_table_style() + row_bg))

    chart_png = _make_aging_chart_png(aging)
    chart_img = Image(io.BytesIO(chart_png), width=5.8*inch, height=2.6*inch)

    return [
        KeepTogether([
            Paragraph("Aging Report", styles["SectionTitle"]),
            Paragraph(
                f'Outstanding balances grouped by days overdue. '
                f'Total overdue: {_fmt_money(aging["total_overdue"])}',
                styles["Muted"]),
            tbl,
            Spacer(1, 8),
            chart_img,
        ]),
        Spacer(1, 10),
    ]


# ---------------------------------------------------------------------------
# Job breakdown
# ---------------------------------------------------------------------------

ROWS_PER_CHUNK = 40   # filas por tabla para evitar superposición con 300+ docs


def _job_breakdown_table(job_rows: list[dict], styles: dict, show_total: bool = False) -> Table:
    """Builds a single job breakdown table for a slice of job_rows."""
    S = styles
    hdr = [Paragraph(h, S["CellHdr"]) for h in [
        "Job ID", "Type",
        "Invoiced", "Collected", "Inv Bal",
        "Billed",   "Paid",      "Bill Bal",
        "Gross Profit", "Status",
    ]]
    data = [hdr]
    row_cmds = []

    for i, j in enumerate(job_rows, start=1):
        status = j["status"]
        sc = JOB_STATUS_COLORS.get(status, TEXT_MUTED)
        net_c = EMERALD if j["gross_profit"] >= 0 else RED_ACC

        if status == "Overdue":
            row_cmds.append(("BACKGROUND", (0, i), (-1, i), RED_LIGHT))

        data.append([
            Paragraph(j["job_id"],                    S["Cell"]),
            Paragraph(j["job_type"] or "—",           S["CellC"]),
            Paragraph(_fmt_money(j["inv_total"]),      S["CellR"]),
            Paragraph(_fmt_money(j["inv_collected"]),  S["CellR"]),
            Paragraph(_fmt_money(j["inv_balance"]),    S["CellR"]),
            Paragraph(_fmt_money(j["bill_total"]),     S["CellR"]),
            Paragraph(_fmt_money(j["bill_paid"]),      S["CellR"]),
            Paragraph(_fmt_money(j["bill_balance"]),   S["CellR"]),
            Paragraph(
                f'<font color="{net_c.hexval()}">{_fmt_money(j["gross_profit"])}</font>',
                S["CellR"]),
            Paragraph(
                f'<font color="{sc.hexval()}"><b>{status}</b></font>',
                S["CellC"]),
        ])

    if show_total:
        total_inv = sum(j["inv_total"] for j in job_rows)
        total_coll = sum(j["inv_collected"] for j in job_rows)
        total_ibal = sum(j["inv_balance"] for j in job_rows)
        total_bill = sum(j["bill_total"] for j in job_rows)
        total_paid = sum(j["bill_paid"] for j in job_rows)
        total_bbal = sum(j["bill_balance"] for j in job_rows)
        total_gp = round(total_coll - total_paid, 2)
        net_c = EMERALD if total_gp >= 0 else RED_ACC

        data.append([
            Paragraph("TOTAL",                    S["CellB"]),
            Paragraph("",                         S["Cell"]),
            Paragraph(_fmt_money(total_inv),      S["CellRB"]),
            Paragraph(_fmt_money(total_coll),     S["CellRB"]),
            Paragraph(_fmt_money(total_ibal),     S["CellRB"]),
            Paragraph(_fmt_money(total_bill),     S["CellRB"]),
            Paragraph(_fmt_money(total_paid),     S["CellRB"]),
            Paragraph(_fmt_money(total_bbal),     S["CellRB"]),
            Paragraph(
                f'<font color="{net_c.hexval()}">{_fmt_money(total_gp)}</font>',
                S["CellRB"]),
            Paragraph("", S["Cell"]),
        ])

    col_w = [0.80*inch, 0.42*inch,
             0.78*inch, 0.78*inch, 0.72*inch,
             0.78*inch, 0.72*inch, 0.72*inch,
             0.80*inch, 0.68*inch]

    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_table_style() + row_cmds))
    return tbl


def _build_job_breakdown_section(job_breakdown: list[dict], styles: dict) -> list:
    if not job_breakdown:
        return [Paragraph("Job Breakdown", styles["SectionTitle"]),
                Paragraph("No job data available.", styles["Muted"]),
                Spacer(1, 6)]

    overdue = sum(1 for j in job_breakdown if j["status"] == "Overdue")
    settled = sum(1 for j in job_breakdown if j["status"] == "Settled")
    partial = sum(1 for j in job_breakdown if j["status"] == "Partial")
    total_gp = round(sum(j["gross_profit"] for j in job_breakdown), 2)
    net_c = EMERALD if total_gp >= 0 else RED_ACC

    story = [
        Paragraph("Job Breakdown", styles["SectionTitle"]),
        Paragraph(
            f'{len(job_breakdown)} jobs  •  Settled: {settled}  •  '
            f'Partial: {partial}  •  Overdue: {overdue}  •  '
            f'Gross Profit: {_fmt_money(total_gp)}',
            styles["Muted"]),
        Spacer(1, 4),
    ]

    # Split into chunks to avoid oversized tables with 300+ documents
    chunks = [job_breakdown[i:i + ROWS_PER_CHUNK]
              for i in range(0, len(job_breakdown), ROWS_PER_CHUNK)]

    for idx, chunk in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        story.append(_job_breakdown_table(chunk, styles, show_total=is_last))
        story.append(Spacer(1, 6))

    return story


# ---------------------------------------------------------------------------
# Document table (Invoices / Bills)
# ---------------------------------------------------------------------------

def _doc_table_chunk(chunk: list[dict], styles: dict,
                     show_total: bool = False,
                     tot_amt: float = 0, tot_coll: float = 0, tot_bal: float = 0) -> Table:
    """Builds a single document table for a slice of rows."""
    S = styles
    hdr = [Paragraph(h, S["CellHdr"]) for h in
           ["Job ID", "Ref / Vendor", "Due Date", "Total", "Collected", "Balance", "% Paid", "Status"]]
    data = [hdr]
    row_cmds = []

    for i, r in enumerate(chunk, start=1):
        status = r["status"]
        sc = STATUS_COLORS.get(status, TEXT_MUTED)
        bg = STATUS_BG_COLORS.get(status, colors.white)
        row_cmds.append(("BACKGROUND", (-1, i), (-1, i), bg))

        data.append([
            Paragraph(r["job_id"] or "—",
                      S["Cell"]),
            Paragraph(r["job_ref_qbo"] or r["vendor_customer"]
                      or "—", S["Cell"]),
            Paragraph(r["due_date"] or "—",
                      S["CellC"]),
            Paragraph(_fmt_money(r["total_amount"]),
                      S["CellR"]),
            Paragraph(_fmt_money(r["collected_amount"]
                                 ),                S["CellR"]),
            Paragraph(_fmt_money(r["balance_amount"]),
                      S["CellR"]),
            Paragraph(_fmt_pct(r["pct_paid"]),
                      S["CellR"]),
            Paragraph(
                f'<font color="{sc.hexval()}"><b>{status}</b></font>',
                S["CellC"]),
        ])

    if show_total:
        data.append([
            Paragraph("TOTAL",              S["CellB"]),
            Paragraph("",                   S["Cell"]),
            Paragraph("",                   S["Cell"]),
            Paragraph(_fmt_money(tot_amt),  S["CellRB"]),
            Paragraph(_fmt_money(tot_coll), S["CellRB"]),
            Paragraph(_fmt_money(tot_bal),  S["CellRB"]),
            Paragraph(_fmt_pct((tot_coll / tot_amt * 100)
                      if tot_amt else 0), S["CellRB"]),
            Paragraph("",                   S["Cell"]),
        ])

    col_w = [0.80*inch, 1.80*inch, 0.78*inch,
             0.88*inch, 0.88*inch, 0.88*inch,
             0.58*inch, 0.74*inch]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_table_style() + row_cmds))
    return tbl


def _build_doc_table(rows: list[dict], doc_label: str, styles: dict) -> list:
    if not rows:
        return [Paragraph(f"{doc_label} (0)", styles["SectionTitle"]),
                Paragraph(
                    f"No {doc_label.lower()} match the selected filters.", styles["Muted"]),
                Spacer(1, 6)]

    active = [r for r in rows if not r["is_voided"]]
    tot_amt = sum(r["total_amount"] for r in active)
    tot_coll = sum(r["collected_amount"] for r in active)
    tot_bal = sum(r["balance_amount"] for r in active)

    color = TEAL_ACC if "Invoice" in doc_label else CORAL_ACC
    story = [
        Paragraph(
            f'<font color="{color.hexval()}">{doc_label}</font>'
            f' <font size="9" color="{TEXT_MUTED.hexval()}">({len(rows)} records  •  '
            f'Total: {_fmt_money(tot_amt)}  •  Collected: {_fmt_money(tot_coll)}  •  '
            f'Balance: {_fmt_money(tot_bal)})</font>',
            styles["SectionTitle"]),
        Spacer(1, 4),
    ]

    chunks = [rows[i:i + ROWS_PER_CHUNK]
              for i in range(0, len(rows), ROWS_PER_CHUNK)]
    for idx, chunk in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        story.append(_doc_table_chunk(
            chunk, styles,
            show_total=is_last,
            tot_amt=tot_amt, tot_coll=tot_coll, tot_bal=tot_bal,
        ))
        story.append(Spacer(1, 6))

    return story


# ---------------------------------------------------------------------------
# Payments table
# ---------------------------------------------------------------------------

def _build_payments_table(rows: list[dict], label: str, styles: dict) -> list:
    if not rows:
        return [Paragraph(f"{label} (0)", styles["SectionTitle"]),
                Paragraph(
                    f"No {label.lower()} match the selected filters.", styles["Muted"]),
                Spacer(1, 6)]

    total = sum(r["total_amount"] for r in rows)
    S = styles
    hdr = [Paragraph(h, S["CellHdr"]) for h in
           ["Reference #", "Payment Date", "Type", "Bank Account", "Amount"]]
    data = [hdr]

    for r in rows:
        data.append([
            Paragraph(r["reference_number"] or "—", S["Cell"]),
            Paragraph(r["date_of_payment"] or "—", S["CellC"]),
            Paragraph(r["type_of_payment"] or "—", S["CellC"]),
            Paragraph(r["bank_account_ref"] or "—", S["Cell"]),
            Paragraph(_fmt_money(r["total_amount"]), S["CellR"]),
        ])

    data.append([
        Paragraph("TOTAL", S["CellB"]),
        Paragraph("",      S["Cell"]),
        Paragraph("",      S["Cell"]),
        Paragraph("",      S["Cell"]),
        Paragraph(_fmt_money(total), S["CellRB"]),
    ])

    col_w = [1.5*inch, 1.0*inch, 1.1*inch, 2.9*inch, 0.9*inch]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(_base_table_style()))

    color = BLUE_ACC if "Invoice" in label else CORAL_ACC
    return [
        KeepTogether([
            Paragraph(
                f'<font color="{color.hexval()}">{label}</font>'
                f' <font size="9" color="{TEXT_MUTED.hexval()}">({len(rows)} records  •  '
                f'Total: {_fmt_money(total)})</font>',
                styles["SectionTitle"]),
            Paragraph(
                "⚠ Amounts shown for reference only — a single payment may cover multiple jobs.",
                styles["Muted"]),
            tbl,
        ]),
        Spacer(1, 10),
    ]


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_financial_report_pdf_bytes(
    data: dict,
    *,
    company_name: str = "Company",
    logo_path: str | None = None,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.55*inch, rightMargin=0.55*inch,
        topMargin=0.45*inch,  bottomMargin=0.55*inch,
        title="Financial Documents Report",
        author=company_name,
    )

    styles = _make_styles()
    filters = data.get("filters", {})
    summary = data.get("summary", {})
    story = []

    # 1. Header
    story.append(_build_header(logo_path, filters, styles))
    accent = Table([[""]], colWidths=[PAGE_W + 0.1*inch],
                   rowHeights=[0.07*inch])
    accent.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GQM_ORANGE)]))
    story.append(accent)
    story.append(Spacer(1, 10))

    # 2. Summary cards
    story.append(Paragraph("Summary", styles["SectionTitle"]))
    story.append(_build_summary_cards(summary, styles))
    story.append(Spacer(1, 12))

    # 3. Monthly breakdown
    story.extend(_build_monthly_section(
        data.get("monthly_breakdown", []), styles))

    # 4. Aging report
    story.extend(_build_aging_section(data.get("aging_report", {}), styles))

    # 5. Donut chart
    donut_png = _make_donut_png(
        summary.get("total_invoiced", 0),
        summary.get("total_billed",   0),
    )
    donut_img = Image(io.BytesIO(donut_png), width=4.5*inch, height=2.8*inch)
    story.append(KeepTogether([
        Paragraph("Invoice vs Bill Distribution", styles["SectionTitle"]),
        Paragraph("Total amounts by document type.", styles["Muted"]),
        donut_img,
    ]))
    story.append(Spacer(1, 10))

    # 6. Job breakdown
    story.extend(_build_job_breakdown_section(
        data.get("job_breakdown", []), styles))

    # 7. Detail sections
    doc_type = filters.get("doc_type", "all")

    if doc_type in ("all", "invoices"):
        story.extend(_build_doc_table(
            data.get("invoices", []), "Invoices", styles))

    if doc_type in ("all", "bills"):
        story.extend(_build_doc_table(data.get("bills", []), "Bills", styles))

    if doc_type in ("all", "invoice_payments"):
        story.extend(_build_payments_table(
            data.get("inv_payments", []), "Invoice Payments", styles))

    if doc_type in ("all", "bill_payments"):
        story.extend(_build_payments_table(
            data.get("bill_payments", []), "Bill Payments", styles))

    # Page numbers
    def _on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawRightString(PAGE_W + 0.55*inch, 0.35 *
                               inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
