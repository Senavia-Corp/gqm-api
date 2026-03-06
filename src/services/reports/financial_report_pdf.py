# src/services/reports/financial_report_pdf.py
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
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
    HRFlowable,
)
from reportlab.lib.utils import ImageReader

# ---------------------------------------------------------------------------
# Brand palette (matches jobs_report_pdf.py)
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

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

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


def _make_bar_chart_png(monthly: list[dict]) -> bytes:
    """
    Grouped bar chart: Invoices Due · Bills Due · Payments Collected per month.
    Only plots months that have data.
    """
    if not monthly:
        fig, ax = plt.subplots(figsize=(7, 3), dpi=150)
        ax.text(0.5, 0.5, "No monthly data available",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    labels    = [r["month_name"][:3] for r in monthly]
    inv_due   = [r["invoices_due"]     for r in monthly]
    bill_due  = [r["bills_due"]        for r in monthly]
    inv_paid  = [r["invoice_payments"] for r in monthly]
    bill_paid = [r["bill_payments"]    for r in monthly]
    collected = [a + b for a, b in zip(inv_paid, bill_paid)]

    x = range(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(7.4, 3.4), dpi=160)

    ax.bar([i - width for i in x], inv_due,   width, label="Invoiced",   color="#059669", alpha=0.85)
    ax.bar([i         for i in x], bill_due,  width, label="Billed",     color="#EA580C", alpha=0.85)
    ax.bar([i + width for i in x], collected, width, label="Collected",  color="#2563EB", alpha=0.85)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"${v/1000:.0f}k" if v >= 1000 else f"${v:.0f}")
    )
    ax.tick_params(axis="y", labelsize=7)
    ax.legend(fontsize=7, frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title("Monthly Financial Overview", fontsize=10, fontweight="bold", pad=8)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _make_donut_png(inv_total: float, bill_total: float) -> bytes:
    """Donut: Invoice vs Bill split."""
    if inv_total == 0 and bill_total == 0:
        inv_total = bill_total = 1  # placeholder

    fig = plt.figure(figsize=(4.2, 2.8), dpi=160)
    ax = fig.add_subplot(111)

    values = [inv_total, bill_total]
    labels_pct = [
        f"Invoices  ({inv_total/(inv_total+bill_total)*100:.1f}%)",
        f"Bills  ({bill_total/(inv_total+bill_total)*100:.1f}%)",
    ]
    wedge_colors = ["#059669", "#EA580C"]

    wedges, _ = ax.pie(
        values,
        startangle=90,
        labels=None,
        autopct=None,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1},
        colors=wedge_colors,
    )
    ax.axis("equal")
    ax.legend(wedges, labels_pct, loc="center left",
              bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=8)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Style factory
# ---------------------------------------------------------------------------

def _make_styles():
    base = getSampleStyleSheet()

    H1 = ParagraphStyle(
        "FH1", parent=base["Title"],
        fontName="Helvetica-Bold", fontSize=17, leading=20,
        textColor=colors.white, alignment=1, spaceAfter=2,
    )
    SmallWhite = ParagraphStyle(
        "FSmallWhite", parent=base["Normal"],
        fontName="Helvetica", fontSize=8, leading=10,
        textColor=colors.white, alignment=1,
    )
    SectionTitle = ParagraphStyle(
        "FSectionTitle", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=11, leading=13,
        textColor=GQM_GREEN, spaceBefore=10, spaceAfter=5,
    )
    Muted = ParagraphStyle(
        "FMuted", parent=base["Normal"],
        fontName="Helvetica", fontSize=8, leading=10,
        textColor=TEXT_MUTED, spaceAfter=4,
    )
    CardLabel = ParagraphStyle(
        "FCardLabel", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=GQM_GREEN, spaceAfter=2,
    )
    CardValue = ParagraphStyle(
        "FCardValue", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=16, leading=18,
        textColor=colors.black, spaceAfter=0,
    )
    CardSub = ParagraphStyle(
        "FCardSub", parent=base["Normal"],
        fontName="Helvetica", fontSize=7, leading=9,
        textColor=TEXT_MUTED, spaceAfter=0,
    )
    TableCell = ParagraphStyle(
        "FTableCell", parent=base["Normal"],
        fontName="Helvetica", fontSize=7.5, leading=9,
        textColor=colors.black,
    )
    TableHeader = ParagraphStyle(
        "FTableHeader", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=GQM_GREEN,
    )

    return {
        "H1": H1, "SmallWhite": SmallWhite,
        "SectionTitle": SectionTitle, "Muted": Muted,
        "CardLabel": CardLabel, "CardValue": CardValue, "CardSub": CardSub,
        "TableCell": TableCell, "TableHeader": TableHeader,
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

_COMMON_TABLE_STYLE = TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0),  TABLE_HEADER),
    ("TEXTCOLOR",    (0, 0), (-1, 0),  GQM_GREEN),
    ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("GRID",         (0, 0), (-1, -1), 0.4, TABLE_GRID),
    ("ALIGN",        (0, 0), (-1, -1), "LEFT"),
    ("ALIGN",        (2, 1), (-1, -1), "RIGHT"),   # numeric cols right
    ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ("ROWBACKGROUNDS",(0, 1),(-1, -1), [colors.white, LIGHT_BG]),
    ("FONTSIZE",     (0, 0), (-1, -1), 7.5),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ("TOPPADDING",   (0, 0), (-1, -1), 5),
    ("LEFTPADDING",  (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
])


def _build_header(logo_path: str | None, filters: dict, styles: dict) -> Table:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    type_txt  = filters.get("type") or "ALL"
    year_txt  = filters.get("year") or "ALL"
    month_num = filters.get("month")
    month_txt = MONTH_NAMES[month_num] if month_num else "ALL"
    doc_txt   = (filters.get("doc_type") or "all").upper()

    meta_line = (
        f"Type: {type_txt}  •  Year: {year_txt}  •  Month: {month_txt}  •  "
        f"Docs: {doc_txt}  •  Generated: {generated}"
    )

    logo_cell: object = Paragraph("", getSampleStyleSheet()["Normal"])
    if logo_path:
        p = Path(logo_path)
        if p.exists():
            logo_cell = _fit_logo(str(p), max_w=1.55 * inch, max_h=0.75 * inch)

    header_tbl = Table(
        [[logo_cell, Paragraph("Financial Documents Report", styles["H1"]),
          Paragraph(meta_line, styles["SmallWhite"])]],
        colWidths=[1.7 * inch, 3.5 * inch, 2.4 * inch],
        rowHeights=[0.85 * inch],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GQM_GREEN),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (0, 0), (0,  0),  "LEFT"),
        ("ALIGN",      (1, 0), (1,  0),  "CENTER"),
        ("ALIGN",      (2, 0), (2,  0),  "RIGHT"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    return header_tbl


def _build_summary_cards(summary: dict, styles: dict) -> Table:
    """2-row grid of 4 KPI cards each."""
    def card(label: str, value: str, sub: str = "", accent: colors.Color = GQM_GREEN):
        return [
            Paragraph(label, styles["CardLabel"]),
            Spacer(1, 3),
            Paragraph(f'<font color="{accent.hexval()}">{value}</font>', styles["CardValue"]),
            Paragraph(sub, styles["CardSub"]),
        ]

    inv_pct  = _fmt_pct(summary["avg_invoice_pct_paid"])
    bill_pct = _fmt_pct(summary["avg_bill_pct_paid"])

    row1 = [
        card("Total Invoiced",   _fmt_money(summary["total_invoiced"]),
             f'{summary["invoice_count"]} invoices  •  avg {inv_pct} paid', EMERALD),
        card("Total Billed",     _fmt_money(summary["total_billed"]),
             f'{summary["bill_count"]} bills  •  avg {bill_pct} paid', ORANGE_ACC),
        card("Total Collected",  _fmt_money(summary["total_collected"]),
             f'Inv payments: {_fmt_money(summary["inv_payment_total"])}  •  '
             f'Bill payments: {_fmt_money(summary["bill_payment_total"])}', BLUE_ACC),
        card("Outstanding Balance", _fmt_money(summary["total_outstanding"]),
             f'Inv: {_fmt_money(summary["invoice_balance"])}  •  '
             f'Bills: {_fmt_money(summary["bill_balance"])}', PURPLE_ACC),
    ]

    tbl = Table(
        [row1],
        colWidths=[1.9 * inch] * 4,
    )
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


def _build_doc_table(rows: list[dict], doc_label: str, styles: dict) -> list:
    """Returns a list of flowables for one document section (Invoice or Bill)."""
    if not rows:
        return [
            Paragraph(f"{doc_label} ({len(rows)})", styles["SectionTitle"]),
            Paragraph(f"No {doc_label.lower()} match the selected filters.", styles["Muted"]),
            Spacer(1, 6),
        ]

    total_amount  = sum(r["total_amount"]  for r in rows)
    total_balance = sum(r["balance_amount"] for r in rows)
    total_paid    = total_amount - total_balance

    header_row = ["Job ID", "Ref / Vendor", "Due Date", "Total", "Balance", "% Paid", "Pmts"]
    data = [header_row]
    for r in rows:
        data.append([
            r["job_id"] or "—",
            r["job_ref_qbo"] or r["vendor_customer"] or "—",
            r["due_date"] or "—",
            _fmt_money(r["total_amount"]),
            _fmt_money(r["balance_amount"]),
            _fmt_pct(r["pct_paid"]),
            str(r["payment_count"]),
        ])
    # Totals footer
    data.append([
        "TOTAL", "", "",
        _fmt_money(total_amount),
        _fmt_money(total_balance),
        _fmt_pct((total_paid / total_amount * 100) if total_amount else 0),
        "",
    ])

    col_w = [0.85*inch, 1.8*inch, 0.75*inch, 0.85*inch, 0.85*inch, 0.6*inch, 0.4*inch]
    tbl = Table(data, colWidths=col_w, repeatRows=1)

    style = TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  TABLE_HEADER),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  GQM_GREEN),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("GRID",         (0, 0), (-1, -2), 0.4, TABLE_GRID),  # skip footer line
        ("ALIGN",        (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0, 1),(-2, -1), [colors.white, LIGHT_BG]),
        ("FONTSIZE",     (0, 0), (-1, -1), 7.5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        # Footer row styling
        ("BACKGROUND",   (0, -1), (-1, -1), GQM_GREEN_2 if False else TABLE_HEADER),
        ("FONTNAME",     (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE",    (0, -1), (-1, -1), 1, GQM_GREEN),
    ])
    tbl.setStyle(style)

    color = EMERALD if "Invoice" in doc_label else ORANGE_ACC

    return [
        KeepTogether([
            Paragraph(
                f'<font color="{color.hexval()}">{doc_label}</font>'
                f' <font size="9" color="{TEXT_MUTED.hexval()}">({len(rows)} records  •  '
                f'Total: {_fmt_money(total_amount)}  •  Collected: {_fmt_money(total_paid)})</font>',
                styles["SectionTitle"],
            ),
            tbl,
        ]),
        Spacer(1, 10),
    ]


def _build_payments_table(rows: list[dict], label: str, styles: dict) -> list:
    """Returns flowables for a payments section (Invoice Payments or Bill Payments)."""
    if not rows:
        return [
            Paragraph(f"{label} ({len(rows)})", styles["SectionTitle"]),
            Paragraph(f"No {label.lower()} match the selected filters.", styles["Muted"]),
            Spacer(1, 6),
        ]

    total = sum(r["total_amount"] for r in rows)

    header_row = ["Reference #", "Payment Date", "Type", "Bank Account", "Amount"]
    data = [header_row]
    for r in rows:
        data.append([
            r["reference_number"] or "—",
            r["date_of_payment"] or "—",
            r["type_of_payment"] or "—",
            r["bank_account_ref"] or "—",
            _fmt_money(r["total_amount"]),
        ])
    data.append(["TOTAL", "", "", "", _fmt_money(total)])

    col_w = [1.4*inch, 1.0*inch, 1.1*inch, 2.0*inch, 0.9*inch]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEADER),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  GQM_GREEN),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -2), 0.4, TABLE_GRID),
        ("ALIGN",         (4, 0), (4, -1),  "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0, 1), (-2, -1), [colors.white, LIGHT_BG]),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE",     (0, -1), (-1, -1), 1, GQM_GREEN),
        ("BACKGROUND",    (0, -1), (-1, -1), TABLE_HEADER),
    ]))

    color = BLUE_ACC if "Invoice" in label else PURPLE_ACC

    return [
        KeepTogether([
            Paragraph(
                f'<font color="{color.hexval()}">{label}</font>'
                f' <font size="9" color="{TEXT_MUTED.hexval()}">({len(rows)} records  •  '
                f'Total: {_fmt_money(total)})</font>',
                styles["SectionTitle"],
            ),
            tbl,
        ]),
        Spacer(1, 10),
    ]


def _build_monthly_section(monthly: list[dict], styles: dict) -> list:
    """Monthly breakdown table + bar chart."""
    if not monthly:
        return [
            Paragraph("Monthly Breakdown", styles["SectionTitle"]),
            Paragraph("No monthly data available for the selected filters.", styles["Muted"]),
        ]

    # Table
    header = ["Month", "Invoiced", "Billed", "Inv Payments", "Bill Payments", "Net Collected"]
    data = [header]
    for r in monthly:
        net = r["invoice_payments"] + r["bill_payments"]
        data.append([
            r["month_name"],
            _fmt_money(r["invoices_due"]),
            _fmt_money(r["bills_due"]),
            _fmt_money(r["invoice_payments"]),
            _fmt_money(r["bill_payments"]),
            _fmt_money(net),
        ])
    # Totals
    data.append([
        "TOTAL",
        _fmt_money(sum(r["invoices_due"]     for r in monthly)),
        _fmt_money(sum(r["bills_due"]        for r in monthly)),
        _fmt_money(sum(r["invoice_payments"] for r in monthly)),
        _fmt_money(sum(r["bill_payments"]    for r in monthly)),
        _fmt_money(sum(r["invoice_payments"] + r["bill_payments"] for r in monthly)),
    ])

    col_w = [1.0*inch, 1.1*inch, 1.1*inch, 1.1*inch, 1.1*inch, 1.1*inch]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEADER),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  GQM_GREEN),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -2), 0.4, TABLE_GRID),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0, 1), (-2, -1), [colors.white, LIGHT_BG]),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE",     (0, -1), (-1, -1), 1, GQM_GREEN),
        ("BACKGROUND",    (0, -1), (-1, -1), TABLE_HEADER),
    ]))

    # Chart
    chart_png = _make_bar_chart_png(monthly)
    chart_img = Image(io.BytesIO(chart_png), width=7.2 * inch, height=3.4 * inch)

    return [
        KeepTogether([
            Paragraph("Monthly Breakdown", styles["SectionTitle"]),
            Paragraph("Grouped by document Due Date (invoices/bills) and Payment Date (payments).", styles["Muted"]),
            tbl,
            Spacer(1, 10),
            chart_img,
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
    """
    Accepts output of get_financial_metrics_data() and returns PDF bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.55 * inch,
        title="Financial Documents Report",
        author=company_name,
    )

    styles  = _make_styles()
    filters = data.get("filters", {})
    summary = data.get("summary", {})
    story   = []

    # 1. Header band
    story.append(_build_header(logo_path, filters, styles))

    # Accent line
    accent = Table([[""]], colWidths=[7.9 * inch], rowHeights=[0.07 * inch])
    accent.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GQM_ORANGE)]))
    story.append(accent)
    story.append(Spacer(1, 10))

    # 2. Summary KPI cards
    story.append(Paragraph("Summary", styles["SectionTitle"]))
    story.append(_build_summary_cards(summary, styles))
    story.append(Spacer(1, 12))

    # 3. Monthly breakdown (always shown)
    story.extend(_build_monthly_section(data.get("monthly_breakdown", []), styles))

    # 4. Donut: Invoice vs Bill split
    donut_png = _make_donut_png(summary.get("total_invoiced", 0), summary.get("total_billed", 0))
    donut_img = Image(io.BytesIO(donut_png), width=4.8 * inch, height=3.0 * inch)

    story.append(KeepTogether([
        Paragraph("Invoice vs Bill Distribution", styles["SectionTitle"]),
        Paragraph("Total amounts by document type.", styles["Muted"]),
        donut_img,
    ]))
    story.append(Spacer(1, 10))

    # 5. Detail sections (respect doc_type filter)
    doc_type = filters.get("doc_type", "all")

    if doc_type in ("all", "invoices"):
        story.extend(_build_doc_table(data.get("invoices", []), "Invoices", styles))

    if doc_type in ("all", "bills"):
        story.extend(_build_doc_table(data.get("bills", []), "Bills", styles))

    if doc_type in ("all", "invoice_payments"):
        story.extend(_build_payments_table(data.get("inv_payments", []), "Invoice Payments", styles))

    if doc_type in ("all", "bill_payments"):
        story.extend(_build_payments_table(data.get("bill_payments", []), "Bill Payments", styles))

    # Page number footer
    def _on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawRightString(7.9 * inch, 0.35 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()