# src/services/metrics/metrics_shared.py
from sqlalchemy import func, extract, and_, or_, case, literal
from ...models.JobModel import Job

# ---------------------------------------------------------------------------
# Status catalogs
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Status buckets
# ---------------------------------------------------------------------------
PENDING_BY_TYPE = {
    "QID": {"Assigned/P. Quote", "Waiting for Approval", "HOLD", "Hold"},
    "PTL": {"Received-Stand By"},
    "PAR": set(),
}

INPROGRESS_BY_TYPE = {
    "QID": {"Scheduled / Work in Progress"},
    "PTL": {"Assigned-In progress"},
    "PAR": {"In Progress"},
}

INPROGRESS_ALL = (
    INPROGRESS_BY_TYPE["QID"]
    | INPROGRESS_BY_TYPE["PTL"]
    | INPROGRESS_BY_TYPE["PAR"]
)

# "Completed" = trabajo terminado, listo para facturar (antes READY_TO_INVOICE)
COMPLETED_BY_TYPE = {
    "QID": {"Completed P. INV / POs"},
    "PTL": {"Completed PVI"},
    "PAR": {"Completed PVI / POs"},
}

CANCELLED_STATUS = "Cancelled"

CLOSED_BY_TYPE = {
    "QID": {"PAID", "Paid"},
    "PAR": {"PAID", "Paid"},
    "PTL": {"Paid", "PAID"},
}

PAID_STATUSES = {"PAID", "Paid"}

# Active statuses for pipeline calculation (Active / uncollected)
ACTIVE_STATUSES = INPROGRESS_ALL

# Full breakdown list (all statuses across all types)
STATUS_BREAKDOWN_LIST = [
    "Assigned/P. Quote",
    "Waiting for Approval",
    "Scheduled / Work in Progress",
    "Cancelled",
    "Completed P. INV / POs",
    "Invoiced",
    "HOLD",
    "PAID",
    "Warranty",
    "Received-Stand By",
    "Assigned-In progress",
    "Completed PVI",
    "Paid",
    "In Progress",
    "Completed PVI / POs",
]

# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def _norm_status_expr():
    """Returns a CASE expression to unify status names (Paid, Hold)."""
    return case(
        (func.upper(func.trim(Job.Job_status)) == "PAID", "Paid"),
        (func.upper(func.trim(Job.Job_status)) == "HOLD", "Hold"),
        else_=func.trim(Job.Job_status)
    )


def _normalize_status_str(status: str | None) -> str:
    """Python helper to normalize a status string."""
    if not status:
        return "—"
    s_upper = status.strip().upper()
    if s_upper == "PAID":
        return "Paid"
    if s_upper == "HOLD":
        return "Hold"
    return status.strip()


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


# ---------------------------------------------------------------------------
# Year filter helper
# ---------------------------------------------------------------------------

def _apply_year_filter(stmt, job_type: str, year: int):
    """
    Applies year filter based on job type:
    - PTL  -> Estimated_start_date
    - QID/PAR -> Date_assigned
    - ALL  -> OR combining both
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