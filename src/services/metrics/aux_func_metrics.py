from flask import Blueprint, jsonify, request, Response
from sqlalchemy import func, extract, and_, or_, case, literal
from src.models.JobModel import Job
from src.services.metrics.jobs_metrics_service import get_jobs_status_metrics_data, _money_expr
from src.services.reports.jobs_report_pdf import build_jobs_report_pdf_bytes


metrics_bp = Blueprint("metrics_blueprint", __name__, url_prefix="/metrics")


def _safe_int(value: str | None, default: int) -> int:
    try:
        v = int(value) if value is not None else default
    except ValueError:
        return default
    return v


def _type_expr(selected_type: str):
    # condición de tipo para usar dentro de CASE en agregaciones
    if selected_type == "ALL":
        return literal(True)
    return Job.Job_type == selected_type


def _year_expr(selected_type: str, year: int | None):
    # condición de año para usar dentro de CASE en agregaciones
    if year is None:
        return literal(True)

    if selected_type == "PTL":
        return and_(
            Job.Estimated_start_date.is_not(None),
            extract("year", Job.Estimated_start_date) == year,
        )

    if selected_type in ("QID", "PAR"):
        return and_(
            Job.Date_assigned.is_not(None),
            extract("year", Job.Date_assigned) == year,
        )

    # ALL -> depende del tipo del job
    return or_(
        and_(
            Job.Job_type == "PTL",
            Job.Estimated_start_date.is_not(None),
            extract("year", Job.Estimated_start_date) == year,
        ),
        and_(
            Job.Job_type != "PTL",
            Job.Date_assigned.is_not(None),
            extract("year", Job.Date_assigned) == year,
        ),
    )


def _sum_if(cond):
    # SUM(CASE WHEN cond THEN 1 ELSE 0 END)
    return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)


def _sum_money_if(cond):
    return func.coalesce(func.sum(case((cond, _money_expr()), else_=0.0)), 0.0)


def _year_expr_any_job(year: int):
    """
    Year predicate independiente del filtro type (depende del Job.Job_type):
    - PTL -> Estimated_start_date
    - QID/PAR -> Date_assigned
    """
    return or_(
        and_(
            Job.Job_type == "PTL",
            Job.Estimated_start_date.is_not(None),
            extract("year", Job.Estimated_start_date) == year,
        ),
        and_(
            Job.Job_type != "PTL",
            Job.Date_assigned.is_not(None),
            extract("year", Job.Date_assigned) == year,
        ),
    )


def _norm_order_by(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in ("revenue", "rev", "money"):
        return "revenue"
    return "closed"


# =============================================================================
# NEW ENDPOINT: Reportes en PDF de Jobs
# =============================================================================
@metrics_bp.get("/reports/jobs")
def jobs_report_pdf():
    """
    GET /metrics/reports/jobs?type=ALL|QID|PTL|PAR&year=2025
    Retorna PDF descargable.
    """
    data, err = get_jobs_status_metrics_data(
        request.args.get("type"),
        request.args.get("year"),
    )
    if err:
        payload, status = err
        return jsonify(payload), status

    # Logo (opcional):
    # - recomendado: guardar en repo tipo: src/assets/logo.png
    # - o usar env var REPORT_LOGO_PATH
    logo_path = "src/assets/gqm-logo.png"  # ajusta a tu repo (o None)

    pdf_bytes = build_jobs_report_pdf_bytes(
        data,
        company_name="Senavia Corp",  # o lo que corresponda
        logo_path=logo_path,
    )

    job_type = data.get("type") or "ALL"
    year = data.get("year") or "ALL"
    filename = f"jobs_report_{job_type}_{year}.pdf"

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
