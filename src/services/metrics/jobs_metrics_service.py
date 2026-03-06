# src/services/metrics/jobs_metrics_service.py
from sqlmodel import select
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ...database.db_sqlmodel import get_session
from ...models.JobModel import Job
from .metrics_shared import STATUS_CATALOG, _norm_job_type, _norm_year, _apply_year_filter

def get_jobs_status_metrics_data(job_type_raw: str | None, year_raw: str | None):
    """
    Retorna exactamente lo necesario para PDF (y también sirve para JSON).
    job_type: QID|PTL|PAR|ALL
    year: int o None
    """
    job_type = _norm_job_type(job_type_raw)
    if job_type is None:
        return None, ({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}, 400)

    year = _norm_year(year_raw)
    if year_raw is not None and year is None:
        return None, ({"detail": "Invalid year. Use a valid number like 2025."}, 400)

    # si quieres limitar a 2025/2026
    if year is not None and year not in (2025, 2026):
        return None, ({"detail": "Invalid year. Use 2025 or 2026."}, 400)

    try:
        with get_session() as session:
            stmt = (
                select(
                    Job.Job_status,
                    func.count().label("count"),
                )
                .select_from(Job)
            )

            if job_type != "ALL":
                stmt = stmt.where(Job.Job_type == job_type)

            if year is not None:
                stmt = _apply_year_filter(stmt, job_type, year)

            stmt = stmt.group_by(Job.Job_status)
            db_rows = session.exec(stmt).all()

            total_stmt = select(func.count()).select_from(Job)
            if job_type != "ALL":
                total_stmt = total_stmt.where(Job.Job_type == job_type)
            if year is not None:
                total_stmt = _apply_year_filter(total_stmt, job_type, year)

            total = session.exec(total_stmt).one() or 0

        # catálogo
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

        # map de conteos
        counts_map: dict[str | None, int] = {}
        unknown_found: list[str] = []

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

        # unknown/null
        unknown_count = sum(counts_map.get(s, 0) for s in unknown_found)
        unknown_pct = (unknown_count / total * 100) if total else 0.0
        null_count = counts_map.get(None, 0)

        data = {
            "type": job_type,
            "year": year,
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

        return data, None

    except SQLAlchemyError as e:
        return None, ({"detail": "DB error.", "code": "db_error"}, 500)