# src/services/metrics/metrics_shared.py
from sqlalchemy import func, case
from sqlmodel import select
from ...models.JobModel import Job
from ...models.link_models.JobMember import JobMemberLink
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

# ---------------------------------------------------------------------------
# Pipeline de cotizaciones por miembro  (sección «P/Quote Pipeline per Member»)
# ---------------------------------------------------------------------------
# Estos nombres son EXCLUSIVOS de esa sección. No reutilizan PENDING_BY_TYPE a
# propósito: ese bucket mete `Waiting for Approval` y `HOLD`, y lo consumen los
# KPIs de Communities/Clients/Parent Companies. Tocarlo movería esos KPIs.

# Estado QID que representa una cotización aún por emitir ("Pending Vendor Quote").
PENDING_VENDOR_QUOTE_STATUS = "Assigned/P. Quote"

# Criterio de negocio (22-ago-2026): ESTRICTO — solo el estado que da nombre a la
# sección. La tabla llevaba filtrando por la unión aplanada `PENDING_ALL`, así que
# en producción mostraba 1.843 filas de las cuales 1.697 eran `Waiting for Approval`
# y 93 `HOLD`; el estado del título era el 3% de lo que se veía.
#   - `Waiting for Approval` = la cotización ya salió, decide el cliente.
#   - `HOLD` = congelado a propósito.
# Ninguno de los dos es «por cotizar», que es lo que esta tabla responde.
QUOTE_PIPELINE_BY_TYPE = {
    "QID": {PENDING_VENDOR_QUOTE_STATUS},
    "PTL": {"Received-Stand By"},
    "PAR": set(),   # PAR no tiene etapa de cotización: nace aprobado, entra en In Progress
}

# Quién «es dueño» de la cotización, en orden de preferencia. Para QID el vendedor
# es el Acc Rep y el Mgmt Member solo cubre el hueco cuando no hay Acc Rep (84 QID
# en producción están en ese caso). Misma preferencia que el `rep_map` de
# `jobs_summary` en JobsM.py: "Prefer Acc Rep Selling when both roles exist".
QUOTE_OWNER_ROLE_PREFERENCE = {
    "QID": ["Acc Rep Selling", "Mgmt Member"],
    "PTL": ["Mgmt Member"],
    "PAR": [],
}


def quote_owner_id_expr(job_type: str):
    """`member_id` del ÚNICO dueño de la cotización, por preferencia de rol.

    Antes la tabla unía `job_member` sin más, así que un job con Acc Rep y Mgmt
    Member salía bajo LOS DOS miembros y la suma de la tabla no era el pipeline
    (Paola Colman: 564 como Acc Rep + 520 como Mgmt = 658 filas para 553 jobs).

    Usa `min(member_id)` dentro de cada rol y no `LIMIT 1`: en producción hay 15
    jobs con dos `Acc Rep Selling` y 25 con dos `Mgmt Member`, y sin el `min` el
    dueño sería arbitrario entre ejecuciones.

    Devuelve None si el tipo no tiene etapa de cotización (PAR).
    """
    roles = QUOTE_OWNER_ROLE_PREFERENCE.get(job_type, [])
    if not roles:
        return None

    candidatos = [
        select(func.min(JobMemberLink.member_id))
        .where(JobMemberLink.job_id == Job.ID_Jobs, JobMemberLink.rol == rol)
        .correlate(Job)
        .scalar_subquery()
        for rol in roles
    ]
    return candidatos[0] if len(candidatos) == 1 else func.coalesce(*candidatos)


def universo_cotizaciones(tipos, year=None):
    """Subconsulta `(job_id, owner_id)` con las cotizaciones abiertas de esos tipos.

    Una fila por job y un unico dueno, asi que agrupar por `owner_id` da el
    pipeline real: antes se unia `job_member` por los dos roles y el mismo job
    salia bajo el Acc Rep Y bajo el project manager.
    """
    partes = []
    for tipo in tipos:
        stmt = select(
            Job.ID_Jobs.label("job_id"),
            quote_owner_id_expr(tipo).label("owner_id"),
        ).where(
            Job.Job_type == tipo,
            Job.Job_status.in_(sorted(QUOTE_PIPELINE_BY_TYPE[tipo])),
        )
        partes.append(_apply_year_filter(stmt, tipo, year) if year else stmt)

    combinado = partes[0] if len(partes) == 1 else partes[0].union_all(*partes[1:])
    return combinado.subquery("cotizaciones")
