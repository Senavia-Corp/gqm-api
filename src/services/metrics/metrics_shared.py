from sqlalchemy import func, extract, and_, or_, case, literal
from ...models.JobModel import Job

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