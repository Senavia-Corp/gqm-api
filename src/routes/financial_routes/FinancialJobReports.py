
from flask import Blueprint, jsonify, request, Response
from sqlmodel import Session

from src.database.db_sqlmodel import engine
from src.services.metrics.financial_jobs_service import get_jobs_report_data
from src.services.reports.financial_jobs_pdf import build_job_financial_report

financial_jobs_bp = Blueprint(
    "financial_jobs_blueprint",
    __name__,
    url_prefix="/metrics/jobs",
)

LOGO_PATH = "src/assets/gqm-logo.png"
COMPANY_NAME = "Senavia Corp"


def _parse_filters() -> dict | None:
    """
    Parses and validates query params.
    Returns None if any parameter is invalid.
    """
    try:
        year_raw = request.args.get("year")
        month_raw = request.args.get("month")
        type_raw = request.args.get("type")
        rep_raw = request.args.get("rep")
        client_raw = request.args.get("client_id")

        return {
            "year":      int(year_raw) if year_raw and year_raw not in ("ALL", "") else None,
            "month":     int(month_raw) if month_raw and month_raw not in ("ALL", "") else None,
            "job_type":  type_raw if type_raw and type_raw != "ALL" else None,
            "rep_filter": rep_raw if rep_raw and rep_raw != "ALL" else None,
            "client_id": client_raw if client_raw and client_raw != "ALL" else None,
        }
    except ValueError:
        return None


# =============================================================================
# GET /metrics/jobs/summary
# =============================================================================

@financial_jobs_bp.get("/summary")
def jobs_summary():
    """
    Returns JSON with all 7 report sections.

    Query params:
        year       = 2026 | ALL
        month      = 1-12 | ALL
        type       = QID | PTL | PAR | ALL
        rep        = "Rep Name" | ALL
        client_id  = client ID | ALL
    """
    filters = _parse_filters()
    if filters is None:
        return jsonify({"error": "Invalid year or month — must be integers."}), 400

    try:
        with Session(engine) as session:
            data = get_jobs_report_data(session, **filters)
        return jsonify(data), 200

    except Exception as e:
        return jsonify({"error": "Internal server error.", "detail": str(e)}), 500


# =============================================================================
# GET /metrics/jobs/reports/pdf
# =============================================================================

@financial_jobs_bp.get("/reports/pdf")
def jobs_report_pdf():
    """
    Returns a downloadable PDF with the full 7-section Jobs Financial Report.

    Same query params as /summary.
    """
    filters = _parse_filters()
    if filters is None:
        return jsonify({"error": "Invalid parameters."}), 400

    try:
        with Session(engine) as session:
            data = get_jobs_report_data(session, **filters)

        pdf_bytes = build_job_financial_report(
            data,
            company_name=COMPANY_NAME,
            logo_path=LOGO_PATH,
        )

        f = data.get("filters", {})
        year_slug = f.get("year") or "ALL"
        month_slug = f.get("month") or "ALL"
        type_slug = f.get("job_type") or "ALL"
        filename = f"Jobs_Report_{type_slug}_{year_slug}_{month_slug}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length":      str(len(pdf_bytes)),
                "Cache-Control":       "no-cache, no-store, must-revalidate",
                "Pragma":              "no-cache",
                "Expires":             "0",
            },
        )

    except Exception as e:
        return jsonify({"error": "Internal server error.", "detail": str(e)}), 500
