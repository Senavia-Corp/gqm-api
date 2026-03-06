# src/routes/financial_metrics_bp.py
from flask import Blueprint, jsonify, request, Response

from ..services.metrics.financial_metrics_service import get_financial_metrics_data
from ..services.reports.financial_report_pdf import build_financial_report_pdf_bytes

financial_metrics_bp = Blueprint(
    "financial_metrics_blueprint", __name__, url_prefix="/metrics/financial"
)

# Optional: adjust to your actual logo path or use an env var
LOGO_PATH    = "src/assets/gqm-logo.png"
COMPANY_NAME = "Senavia Corp"


# =============================================================================
# GET /metrics/financial/summary
# JSON endpoint — consumible desde el dashboard frontend
#
# Query params:
#   type      = QID | PTL | PAR | ALL          (required)
#   year      = 2026 | ALL                     (optional, default ALL)
#   month     = 1-12 | ALL                     (optional, default ALL)
#   doc_type  = invoices | bills |
#               invoice_payments | bill_payments | all  (optional, default all)
# =============================================================================
@financial_metrics_bp.get("/summary")
def financial_summary():
    """
    GET /metrics/financial/summary
    Returns JSON with summary KPIs, monthly breakdown, and document lists.
    """
    data, err = get_financial_metrics_data(
        job_type_raw = request.args.get("type"),
        year_raw     = request.args.get("year"),
        month_raw    = request.args.get("month"),
        doc_type_raw = request.args.get("doc_type"),
    )
    if err:
        payload, status = err
        return jsonify(payload), status

    return jsonify(data), 200


# =============================================================================
# GET /metrics/financial/reports/pdf
# PDF endpoint — returns a downloadable file
#
# Same query params as /summary
# =============================================================================
@financial_metrics_bp.get("/reports/pdf")
def financial_report_pdf():
    """
    GET /metrics/financial/reports/pdf
    Returns a downloadable PDF report.
    """
    data, err = get_financial_metrics_data(
        job_type_raw = request.args.get("type"),
        year_raw     = request.args.get("year"),
        month_raw    = request.args.get("month"),
        doc_type_raw = request.args.get("doc_type"),
    )
    if err:
        payload, status = err
        return jsonify(payload), status

    pdf_bytes = build_financial_report_pdf_bytes(
        data,
        company_name=COMPANY_NAME,
        logo_path=LOGO_PATH,
    )

    filters   = data.get("filters", {})
    type_slug = filters.get("type") or "ALL"
    year_slug = filters.get("year") or "ALL"
    month_num = filters.get("month")
    month_slug = f"M{month_num:02d}" if month_num else "ALL"
    doc_slug  = (filters.get("doc_type") or "all").upper()

    filename = f"financial_report_{type_slug}_{year_slug}_{month_slug}_{doc_slug}.pdf"

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )