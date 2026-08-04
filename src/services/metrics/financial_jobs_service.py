# src/services/metrics/financial_jobs_service.py
from __future__ import annotations

from sqlmodel import Session, select
from sqlalchemy import func, extract, cast, Integer, Date, case, and_
from datetime import datetime

from src.models.JobModel import Job
from src.models.link_models.JobMember import JobMemberLink
from src.models.MemberModel import Member
from src.models.ClientModel import Client

from .metrics_shared import PAID_STATUSES, ACTIVE_STATUSES
from .jobs_metrics_service import _pct_col_expr, _final_col_expr


# Orden lógico para la visualización en el reporte (basado en el flujo de trabajo real)
STATUS_ORDER = [
    "Received-Stand By", "HOLD", "Assigned/P. Quote", "Waiting for Approval",
    "Scheduled / Work in Progress", "Assigned-In progress", "In Progress",
    "Completed P. INV / POs", "Completed PVI / POs", "Completed PVI",
    "Invoiced", "PAID", "Paid", "Warranty", "Cancelled"
]


# ---------------------------------------------------------------------------
# Filter helper
# ---------------------------------------------------------------------------

def _apply_filters(stmt, year: int | None, month: int | None,
                   job_type: str | None, client_id: str | None,
                   rep_filter: str | None = None):
    """Applies common filters to any Job-based statement."""
    effective_date = func.coalesce(
        Job.Date_assigned,
        Job.Estimated_start_date)

    if year is not None:
        stmt = stmt.where(extract("year", cast(effective_date, Date)) == year)
    if month is not None:
        stmt = stmt.where(
            extract("month", cast(effective_date, Date)) == month)
    if job_type:
        stmt = stmt.where(Job.Job_type == job_type)
    if client_id:
        stmt = stmt.where(Job.ID_Client == client_id)
    if rep_filter:
        roles_to_use = ["Mgmt Member"] if job_type == "PTL" else (["Acc Rep Selling"] if job_type in ("QID", "PAR") else ["Acc Rep Selling", "Mgmt Member"])
        stmt = stmt.join(JobMemberLink, JobMemberLink.job_id == Job.ID_Jobs) \
                   .join(Member, Member.ID_Member == JobMemberLink.member_id) \
                   .where(JobMemberLink.rol.in_(roles_to_use)) \
                   .where(Member.Member_Name == rep_filter)
    return stmt


# ---------------------------------------------------------------------------
# Format helpers (used inside the service for derived fields)
# ---------------------------------------------------------------------------

def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _pct(num: float, den: float) -> float:
    return round((num / den), 4) if den else 0.0


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

def get_jobs_report_data(
    session: Session,
    *,
    year: int | None = None,
    month: int | None = None,
    job_type: str | None = None,
    client_id: str | None = None,
    rep_filter: str | None = None,   # filter by rep name (optional)
) -> dict:
    """
    Returns all data needed to build the 7-section Jobs Financial Report.

    Sections:
        1. filters   — echo of applied filters
        2. summary   — 8 KPI cards
        3. monthly   — month-by-month breakdown
        4. quarterly — quarter-by-quarter breakdown
        5. rep       — performance by Acc Rep Selling
        6. status    — distribution & pipeline
        7. service   — profitability by service type
        8. jobs      — full job detail table
    """

    # ------------------------------------------------------------------
    # 1. SUMMARY KPIs
    # ------------------------------------------------------------------
    paid_flag = cast(Job.Job_status.in_(list(PAID_STATUSES)), Integer)

    # Mismas expresiones que el dashboard de Jobs (jobs_metrics_service):
    # el PDF y las tarjetas deben reportar números idénticos para KPIs homónimos.
    pct_col = _pct_col_expr(job_type if job_type and job_type != "ALL" else None)
    pct_label = "Target Return %" if job_type in ("PTL", "PAR") else "Avg Final %"
    final_col = _final_col_expr(job_type or "ALL")

    # H-1/H-2: cancelados fuera de cotizado/fórmula/conteo (mismo criterio que el dashboard)
    alive = func.upper(func.trim(func.coalesce(Job.Job_status, ""))) != "CANCELLED"
    paid_with_pct = and_(
        Job.Job_status.in_(list(PAID_STATUSES)),
        pct_col.is_not(None),
    )

    stmt_sum = select(
        func.sum(case((alive, 1), else_=0)).label("job_count"),
        func.count(Job.ID_Jobs).label("job_count_all"),
        func.sum(case((alive, Job.Gqm_target_sold_pricing), else_=0.0)).label("total_quoted"),
        func.sum(case((alive, Job.Gqm_formula_pricing), else_=0.0)).label("total_formula"),
        func.sum(case((alive, Job.Gqm_adj_formula_pricing), else_=0.0)).label("total_adj_formula"),
        func.sum(case((Job.Job_status.in_(list(PAID_STATUSES)), final_col), else_=0)).label("total_final"),
        func.sum(case((Job.Job_status.in_(list(PAID_STATUSES)), Job.Gqm_premium_in_money), else_=0)).label("total_premium"),
        # H-5: ponderado por monto de los pagados con pct disponible (= dashboard)
        func.coalesce(
            func.sum(case((paid_with_pct, final_col * pct_col), else_=0)) /
            func.nullif(func.sum(case((paid_with_pct, final_col), else_=0)), 0),
            0.0
        ).label("avg_final_pct"),
        func.avg(case((Job.Job_status.in_(list(ACTIVE_STATUSES)), Job.Gqm_target_return), else_=None)).label("avg_target_ret"),
        func.sum(paid_flag).label("paid_count"),
    )
    stmt_sum = _apply_filters(stmt_sum, year, month, job_type, client_id)
    r = session.exec(stmt_sum).first()

    total_quoted = _safe_float(r.total_quoted)
    total_final = _safe_float(r.total_final)
    job_count = int(r.job_count or 0)
    job_count_all = int(r.job_count_all or 0)
    paid_count = int(r.paid_count or 0)

    summary = {
        "job_count":       job_count,
        "paid_count":      paid_count,
        "total_quoted":    total_quoted,
        "total_formula":   _safe_float(r.total_formula),
        "total_adj_formula": _safe_float(r.total_adj_formula),
        "total_final_sold":  total_final,
        "total_premium":   _safe_float(r.total_premium),
        "avg_final_pct":   _safe_float(r.avg_final_pct),
        "avg_target_ret":  _safe_float(r.avg_target_ret),
        "final_vs_quoted_pct": _pct(total_final, total_quoted),
    }

    # ------------------------------------------------------------------
    # 2. MONTHLY BREAKDOWN
    # ------------------------------------------------------------------
    effective_date = func.coalesce(Job.Date_assigned, Job.Estimated_start_date)
    month_key = func.to_char(effective_date, "YYYY-MM")
    month_name = func.to_char(effective_date, "Month")

    stmt_mon = select(
        month_key.label("month"),
        func.max(month_name).label("month_name"),
        func.count(Job.ID_Jobs).label("jobs"),
        func.sum(paid_flag).label("paid_jobs"),
        func.sum(Job.Gqm_target_sold_pricing).label("quoted"),
        func.sum(Job.Gqm_formula_pricing).label("formula"),
        func.sum(Job.Gqm_adj_formula_pricing).label("adj_formula"),
        func.sum(case((Job.Job_status.in_(list(PAID_STATUSES)), final_col), else_=0)).label("final_sold"),
        func.sum(case((Job.Job_status.in_(list(PAID_STATUSES)), Job.Gqm_premium_in_money), else_=0)).label("premium"),
        func.avg(pct_col).label("avg_final_pct"),
    ).group_by(month_key).order_by(month_key)

    stmt_mon = _apply_filters(stmt_mon, year, month, job_type, client_id)
    monthly = []
    for row in session.exec(stmt_mon).all():
        q = _safe_float(row.quoted)
        f = _safe_float(row.final_sold)
        monthly.append({
            "month":        row.month or "—",
            "month_name":   (row.month_name or "").strip(),
            "jobs":         int(row.jobs or 0),
            "paid_jobs":    int(row.paid_jobs or 0),
            "quoted":       q,
            "formula":      _safe_float(row.formula),
            "adj_formula":  _safe_float(row.adj_formula),
            "final_sold":   f,
            "premium":      _safe_float(row.premium),
            "avg_final_pct": _safe_float(row.avg_final_pct),
            "final_pct":    _pct(f, q),
        })

    # ------------------------------------------------------------------
    # 3. QUARTERLY BREAKDOWN
    # ------------------------------------------------------------------
    qtr_key = func.to_char(effective_date, 'YYYY-"Q"Q')

    stmt_qtr = select(
        qtr_key.label("quarter"),
        func.count(Job.ID_Jobs).label("jobs"),
        func.sum(paid_flag).label("paid_jobs"),
        func.sum(Job.Gqm_target_sold_pricing).label("quoted"),
        func.sum(Job.Gqm_formula_pricing).label("formula"),
        func.sum(case((Job.Job_status.in_(list(PAID_STATUSES)), final_col), else_=0)).label("final_sold"),
        func.sum(case((Job.Job_status.in_(list(PAID_STATUSES)), Job.Gqm_premium_in_money), else_=0)).label("premium"),
        func.avg(pct_col).label("avg_final_pct"),
    ).group_by(qtr_key).order_by(qtr_key)

    stmt_qtr = _apply_filters(stmt_qtr, year, month, job_type, client_id)
    quarterly = []
    for row in session.exec(stmt_qtr).all():
        q = _safe_float(row.quoted)
        f = _safe_float(row.final_sold)
        quarterly.append({
            "quarter":       row.quarter or "—",
            "jobs":          int(row.jobs or 0),
            "paid_jobs":     int(row.paid_jobs or 0),
            "quoted":        q,
            "formula":       _safe_float(row.formula),
            "final_sold":    f,
            "premium":       _safe_float(row.premium),
            "avg_final_pct": _safe_float(row.avg_final_pct),
            "final_pct":     _pct(f, q),
        })

    # ------------------------------------------------------------------
    # 4. REP PERFORMANCE
    # ------------------------------------------------------------------
    roles_to_use = ["Mgmt Member"] if job_type == "PTL" else (["Acc Rep Selling"] if job_type in ("QID", "PAR") else ["Acc Rep Selling", "Mgmt Member"])
    rep_label = "Mgmt Member" if job_type == "PTL" else "Rep"

    stmt_rep = (
        select(
            Member.Member_Name.label("rep"),
            func.count(Job.ID_Jobs).label("jobs"),
            func.sum(paid_flag).label("paid"),
            func.sum(Job.Gqm_target_sold_pricing).label("quoted"),
            func.sum(final_col).label("final"),
            func.sum(Job.Gqm_premium_in_money).label("premium"),
            func.avg(pct_col).label("avg_final_pct"),
        )
        .join(JobMemberLink, JobMemberLink.job_id == Job.ID_Jobs)
        .join(Member, Member.ID_Member == JobMemberLink.member_id)
        .where(JobMemberLink.rol.in_(roles_to_use))
        .group_by(Member.Member_Name)
        .order_by(func.sum(final_col).desc())
    )
    stmt_rep = _apply_filters(stmt_rep, year, month, job_type, client_id)

    if rep_filter:
        stmt_rep = stmt_rep.where(Member.Member_Name == rep_filter)

    rep_list = []
    for row in session.exec(stmt_rep).all():
        q = _safe_float(row.quoted)
        f = _safe_float(row.final)
        rep_list.append({
            "rep":           row.rep or "—",
            "jobs":          int(row.jobs or 0),
            "paid":          int(row.paid or 0),
            "quoted":        q,
            "final":         f,
            "premium":       _safe_float(row.premium),
            "avg_final_pct": _safe_float(row.avg_final_pct),
            "final_pct":     _pct(f, q),
        })

    # ------------------------------------------------------------------
    # 5. STATUS DISTRIBUTION & PIPELINE
    # ------------------------------------------------------------------
    stmt_status = select(
        func.trim(Job.Job_status).label("status"),
        func.count(Job.ID_Jobs).label("count"),
            func.sum(Job.Gqm_target_sold_pricing).label("quoted"),
            func.sum(Job.Gqm_final_sold_pricing).label("final"),
            func.sum(Job.Gqm_premium_in_money).label("premium"),
        ).group_by(func.trim(Job.Job_status))

    stmt_status = _apply_filters(stmt_status, year, month, job_type, client_id)

    status_list = []
    pipeline = 0.0

    for row in session.exec(stmt_status).all():
        status_name = (row.status or "UNKNOWN").strip()
        quoted = _safe_float(row.quoted)
        final = _safe_float(row.final)
        count = int(row.count or 0)

        status_list.append({
            "status":  status_name,
            "count":   count,
            "pct":     _pct(count, job_count_all),
            "quoted":  quoted,
            "final":   final,
            "premium": _safe_float(row.premium),
        })

        if status_name in ACTIVE_STATUSES:
            pipeline += quoted

    status_list.sort(key=lambda x: (
        STATUS_ORDER.index(x["status"]) if x["status"] in STATUS_ORDER else 999
    ))

    # ------------------------------------------------------------------
    # 6. SERVICE TYPE PROFITABILITY
    # ------------------------------------------------------------------
    service_list = []
    if job_type not in ("PTL", "PAR"):
        stmt_svc = select(
            Job.Service_type.label("service"),
            func.count(Job.ID_Jobs).label("count"),
            func.sum(final_col).label("final"),
            func.sum(Job.Gqm_premium_in_money).label("premium"),
            func.avg(pct_col).label("avg_final_pct"),
        ).group_by(Job.Service_type)

        stmt_svc = _apply_filters(stmt_svc, year, month, job_type, client_id)

        for row in session.exec(stmt_svc).all():
            service_list.append({
                "service":       row.service or "Unknown",
                "count":         int(row.count or 0),
                "final":         _safe_float(row.final),
                "premium":       _safe_float(row.premium),
                "avg_final_pct": _safe_float(row.avg_final_pct),
            })

        service_list.sort(key=lambda x: x["final"], reverse=True)

    # ------------------------------------------------------------------
    # 7. JOB DETAIL TABLE
    # ------------------------------------------------------------------
    stmt_jobs = (
        select(Job, Client)
        .outerjoin(Client, Client.ID_Client == Job.ID_Client)
        .order_by(Job.Date_assigned.asc().nullslast())
    )
    stmt_jobs = _apply_filters(stmt_jobs, year, month, job_type, client_id)

    raw_jobs = session.exec(stmt_jobs).all()

    # Build rep map in one query to avoid N+1
    job_ids = [row.Job.ID_Jobs for row in raw_jobs]
    rep_map: dict[str, list[str]] = {}
    if job_ids:
        roles_to_use = ["Mgmt Member"] if job_type == "PTL" else (["Acc Rep Selling"] if job_type in ("QID", "PAR") else ["Acc Rep Selling", "Mgmt Member"])
        stmt_reps = (
            select(JobMemberLink.job_id, Member.Member_Name)
            .join(Member, Member.ID_Member == JobMemberLink.member_id)
            .where(
                JobMemberLink.job_id.in_(job_ids),
                JobMemberLink.rol.in_(roles_to_use),
            )
        )
        for j_id, m_name in session.exec(stmt_reps).all():
            rep_map.setdefault(j_id, []).append(m_name or "—")

    job_table = []
    for row in raw_jobs:
        job = row.Job
        client = row.Client
        display_date = job.Date_assigned or job.Estimated_start_date or "—"
        job_table.append({
            "job_id":      job.ID_Jobs,
            "client":      (client.Client_Community if client else "—") or "—",
            "rep":         ", ".join(rep_map.get(job.ID_Jobs, ["—"])),
            "status":      (job.Job_status or "—").strip(),
            "service":     job.Service_type or "—",
            "date": display_date.strftime("%Y-%m-%d") if hasattr(display_date, "strftime") else "—",
            "formula":     _safe_float(job.Gqm_formula_pricing),
            "adj_formula": _safe_float(job.Gqm_adj_formula_pricing),
            "target":      _safe_float(job.Gqm_target_sold_pricing),
            # Revenue PAR = lo facturado (final_sold, fallback a target si 0)
            "final":       _safe_float((job.Gqm_final_sold_pricing or job.Gqm_target_sold_pricing)
                                       if job.Job_type == "PAR" else job.Gqm_final_sold_pricing),
            "pct":         _safe_float(job.Gqm_target_return if job.Job_type in ("PTL", "PAR") else job.Gqm_final_percentage),
            "premium":     _safe_float(job.Gqm_premium_in_money),
        })

    # Sort: OVERDUE first, then by date
    job_table.sort(key=lambda x: (x["status"] != "OVERDUE", x["date"]))

    # ------------------------------------------------------------------
    # FINAL RESPONSE
    # ------------------------------------------------------------------
    return {
        "filters": {
            "year":      year,
            "month":     month,
            "job_type":  job_type,
            "client_id": client_id,
            "rep":       rep_filter,
        },
        "summary":   summary,
        "monthly":   monthly,
        "quarterly": quarterly,
        "rep_label": rep_label,
        "pct_label": pct_label,
        "rep":       rep_list,
        "status":    status_list,
        "pipeline":  round(pipeline, 2),
        "service":   service_list,
        "jobs":      job_table,
    }
