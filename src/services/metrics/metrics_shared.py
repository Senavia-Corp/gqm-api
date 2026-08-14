# src/services/metrics/metrics_shared.py
from sqlalchemy import func, case
from ...models.JobModel import Job
from src.utils.job_app_year import expr_anio_app

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

PENDING_ALL = (
    PENDING_BY_TYPE["QID"]
    | PENDING_BY_TYPE["PTL"]
    | PENDING_BY_TYPE["PAR"]
)

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

COMPLETED_ALL = (
    COMPLETED_BY_TYPE["QID"]
    | COMPLETED_BY_TYPE["PTL"]
    | COMPLETED_BY_TYPE["PAR"]
)

# Incluye In Progress + Completed + Paid (excluye Pending y Cancelled)
AVERAGE_TARGET_RETURN_STATUSES = INPROGRESS_ALL | COMPLETED_ALL | PAID_STATUSES

# Active statuses for pipeline calculation (Active / uncollected)
ACTIVE_STATUSES = INPROGRESS_ALL | {"Invoiced"}

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
    """Filtra por el año de la app de Podio, la regla canónica.

    Antes esto derivaba el año de fechas (`Estimated_start_date` para PTL,
    `Date_assigned` para el resto) con guardas `IS NOT NULL`. Eso perdía filas:
    en producción **43 jobs no cancelados** salían en «All» y en ningún año —
    41 con fecha de nov/dic de 2022 pero viviendo en la app de 2023, y 2 con las
    dos fechas NULL (`PTL3026`, `PTL4027`). El año de Podio es la app en la que
    vive el ítem, no la fecha en que se trabajó.

    `job_type` ya no se usa: el año de app no depende del tipo. Se mantiene en la
    firma porque hay ~13 llamadas y cambiarla no aporta nada.
    """
    return stmt.where(expr_anio_app() == year)