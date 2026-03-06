# src/blueprints/timeline_metrics_bp.py
from __future__ import annotations

from flask import Blueprint, jsonify, request, Response

from ..services.metrics.timeline_metrics_service import get_timeline_metrics_data
from ..services.reports.timeline_report_pdf import build_timeline_pdf

# Adjust to your actual logo path — mirrors financial_metrics_bp.py
LOGO_PATH    = "src/assets/gqm-logo.png"
COMPANY_NAME = "GQM Service"

timeline_metrics_bp = Blueprint(
    "timeline_metrics_blueprint",
    __name__,
    url_prefix="/metrics/timeline",
)


def _get_params() -> tuple[str | None, str, str | None]:
    """Extract and return (job_id, period, ref_date) from query params."""
    job_id   = request.args.get("job_id",   "").strip() or None
    period   = request.args.get("period",   "month").strip().lower()
    ref_date = request.args.get("ref_date", "").strip() or None
    return job_id, period, ref_date


# ---------------------------------------------------------------------------
# GET /metrics/timeline/summary  →  JSON for dashboard / frontend
# ---------------------------------------------------------------------------

@timeline_metrics_bp.get("/summary")
def get_timeline_summary():
    """
    Query params:
      - job_id   (required): e.g. QID6-0001
      - period   (optional): day | week | month  (default: month)
      - ref_date (optional): YYYY-MM-DD reference date (default: today)

    Returns the full metrics dict as JSON.
    """
    job_id, period, ref_date = _get_params()

    if not job_id:
        return jsonify({"error": "job_id is required"}), 400

    data, err = get_timeline_metrics_data(job_id, period, ref_date)

    if err:
        message, status = err
        return jsonify({"error": message}), status

    return jsonify(data), 200


# ---------------------------------------------------------------------------
# GET /metrics/timeline/reports/pdf  →  downloadable PDF
# ---------------------------------------------------------------------------

@timeline_metrics_bp.get("/reports/pdf")
def get_timeline_pdf():
    """
    Query params:
      - job_id   (required): e.g. QID6-0001
      - period   (optional): day | week | month  (default: month)
      - ref_date (optional): YYYY-MM-DD reference date (default: today)
    """
    job_id, period, ref_date = _get_params()

    if not job_id:
        return jsonify({"error": "job_id is required"}), 400

    data, err = get_timeline_metrics_data(job_id, period, ref_date)

    if err:
        message, status = err
        return jsonify({"error": message}), status

    try:
        pdf_bytes = build_timeline_pdf(data, logo_path=LOGO_PATH)
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {e}"}), 500

    start    = data["date_range"]["start"][:10]
    end      = data["date_range"]["end"][:10]
    filename = f"timeline_{job_id}_{period}_{start}_{end}.pdf"

    return Response(
        pdf_bytes,
        status=200,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )