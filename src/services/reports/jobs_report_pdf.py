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
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
)

def _make_pie_png_bytes(rows: list[dict], top_n: int = 8) -> bytes:
    """
    Pie chart con los status más relevantes.
    - top_n: agrupa el resto en "Other" para que sea legible.
    """
    # filtra solo los que tengan count > 0
    data = [(r["status"], int(r["count"])) for r in rows if int(r["count"]) > 0]
    data.sort(key=lambda x: x[1], reverse=True)

    if not data:
        # pie vacío
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

    fig = plt.figure(figsize=(6.5, 3.5), dpi=160)
    ax = fig.add_subplot(111)
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
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
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title="Jobs Report",
        author=company_name,
    )

    styles = getSampleStyleSheet()
    story = []

    # Header (logo + título)
    header_cells = []

    if logo_path:
        p = Path(logo_path)
        if p.exists():
            header_cells.append(Image(str(p), width=1.2*inch, height=1.2*inch))
        else:
            header_cells.append(Paragraph("", styles["Normal"]))
    else:
        header_cells.append(Paragraph("", styles["Normal"]))

    report_title = f"<b>Jobs Report</b><br/>{company_name}"
    subtitle = f"Type: <b>{metrics.get('type')}</b> &nbsp;&nbsp; Year: <b>{metrics.get('year') or 'ALL'}</b><br/>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    header_cells.append(Paragraph(report_title + "<br/>" + subtitle, styles["Title"]))

    header_tbl = Table([header_cells], colWidths=[1.4*inch, 5.6*inch])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 12))

    # Summary
    total = int(metrics.get("total") or 0)
    story.append(Paragraph(f"<b>Total Jobs:</b> {total}", styles["Heading2"]))
    story.append(Spacer(1, 6))

    # Tabla de distribución
    rows = metrics.get("rows") or []
    table_data = [["Status", "Count", "%"]]
    for r in rows:
        table_data.append([r["status"], str(int(r["count"])), f'{float(r["pct"]):.2f}%'])

    dist_tbl = Table(table_data, colWidths=[4.4*inch, 1.0*inch, 1.0*inch])
    dist_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F2F2F2")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.black),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("ALIGN", (1,1), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(Paragraph("Status Distribution", styles["Heading2"]))
    story.append(dist_tbl)
    story.append(Spacer(1, 12))

    # Top 5
    top5 = sorted(rows, key=lambda x: int(x["count"]), reverse=True)[:5]
    top5_data = [["Top 5 Statuses", "Count"]]
    for r in top5:
        top5_data.append([r["status"], str(int(r["count"]))])

    top5_tbl = Table(top5_data, colWidths=[5.4*inch, 1.0*inch])
    top5_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F2F2F2")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("ALIGN", (1,1), (-1,-1), "RIGHT"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFAFA")]),
    ]))
    story.append(top5_tbl)
    story.append(Spacer(1, 12))

    # Pie chart
    story.append(Paragraph("Pie Chart (Status Share)", styles["Heading2"]))
    pie_png = _make_pie_png_bytes(rows, top_n=8)
    pie_img = Image(io.BytesIO(pie_png), width=6.5*inch, height=3.5*inch)
    story.append(pie_img)

    # Footer básico (paginación)
    def _on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(7.9*inch, 0.45*inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)

    return buf.getvalue()