from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy import func, extract, and_, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job, JobType

metrics_bp = Blueprint("metrics_blueprint", __name__, url_prefix="/metrics")

# ---- Catálogos de status por tipo (tal cual los pasaste) ----
STATUS_CATALOG = {
    "QID": [
        "Assigned/P. Quote",
        "Waiting for Approval",
        "Scheduled / Work in Progress",
        "Cancelled",
        "Completed P. INV / POs",
        "Invoiced",
        "HOLD",
        "PAID",
        "Warranty",
    ],
    "PTL": [
        "Received-Stand By",
        "Assigned-In progress",
        "Completed PVI",
        "Cancelled",
        "Paid",
    ],
    "PAR": [
        "In Progress",
        "Completed PVI / POs",
        "Invoiced",
        "PAID",
        "Cancelled",
    ],
}

def _norm_job_type(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().upper()
    if v == "ALL":
        return "ALL"
    if v in ("QID", "PTL", "PAR"):
        return v
    return None

def _norm_year(value: str | None) -> int | None:
    if not value:
        return None
    try:
        y = int(value)
    except ValueError:
        return None
    # rango razonable (ajústalo si quieres)
    if y < 1900 or y > 2100:
        return None
    return y


def _apply_year_filter(stmt, job_type: str, year: int):
    """
    Aplica el filtro de año según el tipo.
    - PTL -> Estimated_start_date
    - QID/PAR -> Date_assigned
    - ALL -> OR combinando ambos criterios
    """
    if job_type == "PTL":
        return stmt.where(
            Job.Estimated_start_date.is_not(None),
            extract("year", Job.Estimated_start_date) == year,
        )

    if job_type in ("QID", "PAR"):
        return stmt.where(
            Job.Date_assigned.is_not(None),
            extract("year", Job.Date_assigned) == year,
        )

    # ALL
    return stmt.where(
        or_(
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
    )


@metrics_bp.get("/jobs/status")
def jobs_status_metrics():
    """
    GET /metrics/jobs/status?type=QID|PTL|PAR|ALL&year=2025
    """
    try:
        job_type = _norm_job_type(request.args.get("type"))
        if job_type is None:
            return jsonify({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}), 400

        year = _norm_year(request.args.get("year"))
        if request.args.get("year") is not None and year is None:
            return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

        with get_session() as session:
            # -------------------------
            # Query base (agregación)
            # -------------------------
            stmt = (
                select(
                    Job.Job_status,
                    func.count().label("count"),
                )
                .select_from(Job)
            )

            # type filter
            if job_type != "ALL":
                stmt = stmt.where(Job.Job_type == job_type)

            # year filter
            if year is not None:
                stmt = _apply_year_filter(stmt, job_type, year)

            stmt = stmt.group_by(Job.Job_status)
            db_rows = session.exec(stmt).all()  # [(status, count), ...]

            # Total (para porcentajes)
            total_stmt = select(func.count()).select_from(Job)

            if job_type != "ALL":
                total_stmt = total_stmt.where(Job.Job_type == job_type)

            if year is not None:
                total_stmt = _apply_year_filter(total_stmt, job_type, year)

            total = session.exec(total_stmt).one() or 0

        # -------------------------
        # Construir respuesta con catálogo
        # -------------------------
        if job_type == "ALL":
            catalog = []
            seen = set()
            for t in ("QID", "PTL", "PAR"):
                for s in STATUS_CATALOG[t]:
                    if s not in seen:
                        catalog.append(s)
                        seen.add(s)
        else:
            catalog = STATUS_CATALOG[job_type]

        counts_map = {}
        unknown_found = []
        for status, count in db_rows:
            key = status if status is not None else None
            counts_map[key] = int(count)
            if key is not None and key not in catalog:
                unknown_found.append(key)

        rows = []
        for s in catalog:
            c = counts_map.get(s, 0)
            pct = (c / total * 100) if total else 0.0
            rows.append({"status": s, "count": c, "pct": round(pct, 2)})

        unknown_count = sum(counts_map.get(s, 0) for s in unknown_found)
        unknown_pct = (unknown_count / total * 100) if total else 0.0

        null_count = counts_map.get(None, 0)

        response = {
            "type": job_type,
            "year": year,  # <- útil para el front
            "total": int(total),
            "rows": rows,
            "unknown_status": {
                "count": int(unknown_count),
                "pct": round(unknown_pct, 2),
                "statuses": unknown_found,
            },
            "null_status": {
                "count": int(null_count),
                "pct": round((null_count / total * 100), 2) if total else 0.0,
            },
        }

        return jsonify(response), 200

    except SQLAlchemyError as db_error:
        print(f"DB error metrics jobs/status: {db_error}")
        return jsonify({"detail": "Error interno del servidor al consultar la base de datos.", "code": "db_error"}), 500
    except Exception as e:
        print(f"Unexpected error metrics jobs/status: {e}")
        return jsonify({"detail": "Error interno inesperado del servidor.", "code": "internal_error"}), 500