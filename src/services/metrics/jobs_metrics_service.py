from __future__ import annotations

from sqlmodel import select
from sqlalchemy import func, extract, cast, Integer, Date, and_, or_, case
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime

from ...database.db_sqlmodel import get_session
from ...models.JobModel import Job
from ...models.ClientModel import Client
from ...models.MemberModel import Member
from ...models.link_models.JobMember import JobMemberLink

from .metrics_shared import (
    STATUS_CATALOG,
    INPROGRESS_BY_TYPE,
    INPROGRESS_ALL,
    COMPLETED_BY_TYPE,
    PAID_STATUSES,
    ACTIVE_STATUSES,
    _norm_job_type,
    _norm_year,
    _apply_year_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _pct(num: float, den: float) -> float:
    return round((num / den), 4) if den else 0.0


def _money_expr():
    """Revenue expression: PAR -> target_sold_pricing, QID/PTL -> final_sold_pricing."""
    return case(
        (Job.Job_type == "PAR", func.coalesce(Job.Gqm_target_sold_pricing, 0.0)),
        else_=func.coalesce(Job.Gqm_final_sold_pricing, 0.0),
    )


def _pct_col_expr(job_type: str | None):
    """Percentage column: PTL/PAR -> target_return, QID/None -> final_percentage."""
    if job_type in ("PTL", "PAR"):
        return Job.Gqm_target_return
    return Job.Gqm_final_percentage


def _final_col_expr(job_type: str | None):
    """Final sold column: PAR -> formula_pricing, others -> final_sold_pricing."""
    if job_type == "PAR":
        return Job.Gqm_formula_pricing
    return Job.Gqm_final_sold_pricing


def _apply_base_filters(stmt, job_type: str | None, year: int | None):
    """Apply type + year filters to a statement."""
    if job_type and job_type != "ALL":
        stmt = stmt.where(Job.Job_type == job_type)
    if year is not None:
        jt = job_type or "ALL"
        stmt = _apply_year_filter(stmt, jt, year)
    return stmt


def _get_inprogress_statuses(job_type: str | None) -> set[str]:
    if job_type and job_type != "ALL":
        return INPROGRESS_BY_TYPE.get(job_type, set())
    return INPROGRESS_ALL


def _get_completed_statuses(job_type: str | None) -> set[str]:
    if job_type and job_type != "ALL":
        return COMPLETED_BY_TYPE.get(job_type, set())
    return COMPLETED_BY_TYPE["QID"] | COMPLETED_BY_TYPE["PTL"] | COMPLETED_BY_TYPE["PAR"]


# ---------------------------------------------------------------------------
# Función Job dashboard
# ---------------------------------------------------------------------------

def get_jobs_dashboard_data(job_type_raw: str | None, year_raw: str | None):
    """
    Returns all data needed for the Jobs Metrics Dashboard.

    Sections:
        1. filters          — echo of applied filters
        2. kpi_summary      — 8 KPI cards
        3. monthly_sales    — month-by-month breakdown (paid jobs by date chart)
        4. quarterly        — quarter-by-quarter breakdown
        5. rep_performance  — performance by Acc Rep Selling / Mgmt Member
        6. status_breakdown — distribution & pipeline indicator
        7. service_type_sales — yearly sales by service type (stacked bar)
        8. in_progress_jobs — listing of jobs In Progress with $ amount
        9. ready_to_invoice — listing of jobs ready to be invoiced
    """
    job_type = _norm_job_type(job_type_raw)
    if job_type is None:
        return None, ({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}, 400)

    year = _norm_year(year_raw)
    if year_raw is not None and year is None:
        return None, ({"detail": "Invalid year. Use a valid number like 2025."}, 400)

    pct_col = _pct_col_expr(job_type if job_type != "ALL" else None)
    pct_label = "Target Return %" if job_type in (
        "PTL", "PAR") else "Avg Final %"
    final_col = _final_col_expr(job_type if job_type != "ALL" else None)

    normed_type = job_type  # "ALL" | "QID" | "PTL" | "PAR"

    try:
        with get_session() as session:

            # ------------------------------------------------------------------
            # 1. KPI SUMMARY
            # ------------------------------------------------------------------
            paid_flag = cast(Job.Job_status.in_(list(PAID_STATUSES)), Integer)

            stmt_sum = select(
                func.count(Job.ID_Jobs).label("job_count"),
                func.sum(Job.Gqm_target_sold_pricing).label("total_quoted"),
                func.sum(Job.Gqm_formula_pricing).label("total_formula"),
                func.sum(Job.Gqm_adj_formula_pricing).label(
                    "total_adj_formula"),
                func.sum(final_col).label("total_final"),
                func.sum(Job.Gqm_premium_in_money).label("total_premium"),
                func.avg(pct_col).label("avg_final_pct"),
                func.avg(Job.Gqm_target_return).label("avg_target_ret"),
                func.sum(paid_flag).label("paid_count"),
            )
            stmt_sum = _apply_base_filters(stmt_sum, normed_type, year)
            r = session.exec(stmt_sum).first()

            total_quoted = _safe_float(r.total_quoted)
            total_final = _safe_float(r.total_final)
            job_count = int(r.job_count or 0)
            paid_count = int(r.paid_count or 0)

            kpi_summary = {
                "job_count":          job_count,
                "paid_count":         paid_count,
                "total_quoted":       total_quoted,
                "total_formula":      _safe_float(r.total_formula),
                "total_adj_formula":  _safe_float(r.total_adj_formula),
                "total_final_sold":   total_final,
                "total_premium":      _safe_float(r.total_premium),
                "avg_final_pct":      _safe_float(r.avg_final_pct),
                "avg_target_ret":     _safe_float(r.avg_target_ret),
                "final_vs_quoted_pct": _pct(total_final, total_quoted),
                "pct_label":          pct_label,
            }

            # ------------------------------------------------------------------
            # 2. MONTHLY SALES (Chart: Paid jobs by date)
            # ------------------------------------------------------------------
            effective_date = func.coalesce(
                Job.Date_assigned, Job.Estimated_start_date)
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
                func.sum(final_col).label("final_sold"),
                func.sum(Job.Gqm_premium_in_money).label("premium"),
                func.avg(pct_col).label("avg_final_pct"),
            ).group_by(month_key).order_by(month_key)

            stmt_mon = _apply_base_filters(stmt_mon, normed_type, year)

            monthly_sales = []
            for row in session.exec(stmt_mon).all():
                q = _safe_float(row.quoted)
                f = _safe_float(row.final_sold)
                monthly_sales.append({
                    "month":         row.month or "—",
                    "month_name":    (row.month_name or "").strip(),
                    "jobs":          int(row.jobs or 0),
                    "paid_jobs":     int(row.paid_jobs or 0),
                    "quoted":        q,
                    "formula":       _safe_float(row.formula),
                    "adj_formula":   _safe_float(row.adj_formula),
                    "final_sold":    f,
                    "premium":       _safe_float(row.premium),
                    "avg_final_pct": _safe_float(row.avg_final_pct),
                    "final_pct":     _pct(f, q),
                })

            # ------------------------------------------------------------------
            # 3. QUARTERLY BREAKDOWN
            # ------------------------------------------------------------------
            qtr_key = func.to_char(
                func.coalesce(Job.Date_assigned, Job.Estimated_start_date),
                'YYYY-"Q"Q'
            )

            stmt_qtr = select(
                qtr_key.label("quarter"),
                func.count(Job.ID_Jobs).label("jobs"),
                func.sum(paid_flag).label("paid_jobs"),
                func.sum(Job.Gqm_target_sold_pricing).label("quoted"),
                func.sum(Job.Gqm_formula_pricing).label("formula"),
                func.sum(final_col).label("final_sold"),
                func.sum(Job.Gqm_premium_in_money).label("premium"),
                func.avg(pct_col).label("avg_final_pct"),
            ).group_by(qtr_key).order_by(qtr_key)

            stmt_qtr = _apply_base_filters(stmt_qtr, normed_type, year)

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
            if normed_type == "PTL":
                roles_to_use = ["Mgmt Member"]
                rep_label = "Mgmt Member"
            elif normed_type in ("QID", "PAR"):
                roles_to_use = ["Acc Rep Selling"]
                rep_label = "Rep"
            else:
                roles_to_use = ["Acc Rep Selling", "Mgmt Member"]
                rep_label = "Rep / Mgmt Member"

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
            stmt_rep = _apply_base_filters(stmt_rep, normed_type, year)

            rep_performance = []
            for row in session.exec(stmt_rep).all():
                q = _safe_float(row.quoted)
                f = _safe_float(row.final)
                rep_performance.append({
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
            # 5. STATUS BREAKDOWN + PIPELINE
            # ------------------------------------------------------------------
            stmt_status = select(
                func.trim(Job.Job_status).label("status"),
                func.count(Job.ID_Jobs).label("count"),
                func.sum(Job.Gqm_target_sold_pricing).label("quoted"),
                func.sum(final_col).label("final"),
                func.sum(Job.Gqm_premium_in_money).label("premium"),
            ).group_by(func.trim(Job.Job_status))

            stmt_status = _apply_base_filters(stmt_status, normed_type, year)

            status_breakdown = []
            pipeline = 0.0

            for row in session.exec(stmt_status).all():
                status_name = (row.status or "UNKNOWN").strip()
                quoted = _safe_float(row.quoted)
                final = _safe_float(row.final)
                count = int(row.count or 0)

                status_breakdown.append({
                    "status":  status_name,
                    "count":   count,
                    "pct":     _pct(count, job_count),
                    "quoted":  quoted,
                    "final":   final,
                    "premium": _safe_float(row.premium),
                })

                if status_name in ACTIVE_STATUSES:
                    pipeline += quoted

            status_breakdown.sort(key=lambda x: x["count"], reverse=True)

            # ------------------------------------------------------------------
            # 6. SERVICE TYPE SALES (Stacked Bar: Yearly Sales by Service Type)
            # ------------------------------------------------------------------
            service_type_sales = []
            if normed_type not in ("PTL", "PAR"):
                stmt_svc = select(
                    Job.Service_type.label("service"),
                    func.count(Job.ID_Jobs).label("count"),
                    func.sum(final_col).label("final"),
                    func.sum(Job.Gqm_premium_in_money).label("premium"),
                    func.avg(pct_col).label("avg_final_pct"),
                    func.sum(paid_flag).label("paid_jobs"),
                ).group_by(Job.Service_type)

                stmt_svc = _apply_base_filters(stmt_svc, normed_type, year)

                for row in session.exec(stmt_svc).all():
                    service_type_sales.append({
                        "service":       row.service or "Unknown",
                        "count":         int(row.count or 0),
                        "final":         _safe_float(row.final),
                        "premium":       _safe_float(row.premium),
                        "avg_final_pct": _safe_float(row.avg_final_pct),
                        "paid_jobs":     int(row.paid_jobs or 0),
                    })

                service_type_sales.sort(key=lambda x: x["final"], reverse=True)

            # ------------------------------------------------------------------
            # 7. IN PROGRESS JOBS (Listing w/ $ amount)
            # ------------------------------------------------------------------
            inprog_statuses = list(_get_inprogress_statuses(normed_type))

            stmt_inprog = (
                select(Job, Client)
                .outerjoin(Client, Client.ID_Client == Job.ID_Client)
                .where(Job.Job_status.in_(inprog_statuses))
                .order_by(func.coalesce(Job.Date_assigned, Job.Estimated_start_date).asc().nullslast())
            )
            stmt_inprog = _apply_base_filters(stmt_inprog, normed_type, year)

            raw_inprog = session.exec(stmt_inprog).all()

            # Batch-load reps for these jobs
            inprog_ids = [row.Job.ID_Jobs for row in raw_inprog]
            inprog_rep_map: dict[str, list[str]] = {}
            if inprog_ids:
                stmt_reps = (
                    select(JobMemberLink.job_id, Member.Member_Name)
                    .join(Member, Member.ID_Member == JobMemberLink.member_id)
                    .where(
                        JobMemberLink.job_id.in_(inprog_ids),
                        JobMemberLink.rol.in_(roles_to_use),
                    )
                )
                for j_id, m_name in session.exec(stmt_reps).all():
                    inprog_rep_map.setdefault(j_id, []).append(m_name)

            in_progress_jobs = []
            for row in raw_inprog:
                job = row.Job
                client = row.Client
                display_date = job.Date_assigned or job.Estimated_start_date
                amount = (
                    _safe_float(job.Gqm_target_sold_pricing)
                    if job.Job_type == "PAR"
                    else _safe_float(job.Gqm_final_sold_pricing)
                )
                in_progress_jobs.append({
                    "job_id":   job.ID_Jobs,
                    "type":     job.Job_type,
                    "client":   client.Client_Community if client else "—",
                    "rep":      ", ".join(inprog_rep_map.get(job.ID_Jobs, ["—"])),
                    "status":   (job.Job_status or "—").strip(),
                    "service":  job.Service_type or "—",
                    "date":     display_date.strftime("%Y-%m-%d") if hasattr(display_date, "strftime") else "—",
                    "amount":   amount,
                    "quoted":   _safe_float(job.Gqm_target_sold_pricing),
                    "premium":  _safe_float(job.Gqm_premium_in_money),
                    "pct":      (
                        _safe_float(job.Gqm_target_return)
                        if job.Job_type in ("PTL", "PAR")
                        else _safe_float(job.Gqm_final_percentage)
                    ),
                })

            # ------------------------------------------------------------------
            # 8. COMPLETED JOBS (Ready to Invoice)
            # ------------------------------------------------------------------
            completed_statuses = list(_get_completed_statuses(normed_type))

            stmt_inv = (
                select(Job, Client)
                .outerjoin(Client, Client.ID_Client == Job.ID_Client)
                .where(Job.Job_status.in_(completed_statuses))
                .order_by(func.coalesce(Job.Date_assigned, Job.Estimated_start_date).asc().nullslast())
            )
            stmt_inv = _apply_base_filters(stmt_inv, normed_type, year)

            raw_inv = session.exec(stmt_inv).all()

            # Batch-load reps for completed jobs
            inv_ids = [row.Job.ID_Jobs for row in raw_inv]
            inv_rep_map: dict[str, list[str]] = {}
            if inv_ids:
                stmt_inv_reps = (
                    select(JobMemberLink.job_id, Member.Member_Name)
                    .join(Member, Member.ID_Member == JobMemberLink.member_id)
                    .where(
                        JobMemberLink.job_id.in_(inv_ids),
                        JobMemberLink.rol.in_(roles_to_use),
                    )
                )
                for j_id, m_name in session.exec(stmt_inv_reps).all():
                    inv_rep_map.setdefault(j_id, []).append(m_name)

            ready_to_invoice = []
            for row in raw_inv:
                job = row.Job
                client = row.Client
                display_date = job.Date_assigned or job.Estimated_start_date
                amount = (
                    _safe_float(job.Gqm_target_sold_pricing)
                    if job.Job_type == "PAR"
                    else _safe_float(job.Gqm_final_sold_pricing)
                )
                ready_to_invoice.append({
                    "job_id":   job.ID_Jobs,
                    "type":     job.Job_type,
                    "client":   client.Client_Community if client else "—",
                    "rep":      ", ".join(inv_rep_map.get(job.ID_Jobs, ["—"])),
                    "status":   (job.Job_status or "—").strip(),
                    "service":  job.Service_type or "—",
                    "date":     display_date.strftime("%Y-%m-%d") if hasattr(display_date, "strftime") else "—",
                    "amount":   amount,
                    "quoted":   _safe_float(job.Gqm_target_sold_pricing),
                    "formula":  _safe_float(job.Gqm_formula_pricing),
                    "adj_formula": _safe_float(job.Gqm_adj_formula_pricing),
                    "premium":  _safe_float(job.Gqm_premium_in_money),
                    "pct":      (
                        _safe_float(job.Gqm_target_return)
                        if job.Job_type in ("PTL", "PAR")
                        else _safe_float(job.Gqm_final_percentage)
                    ),
                })

        # ------------------------------------------------------------------
        # FINAL RESPONSE
        # ------------------------------------------------------------------
        return {
            "filters": {
                "type": normed_type,
                "year": year,
            },
            "kpi_summary":        kpi_summary,
            "monthly_sales":      monthly_sales,
            "quarterly":          quarterly,
            "rep_label":          rep_label,
            "rep_performance":    rep_performance,
            "status_breakdown":   status_breakdown,
            "pipeline":           round(pipeline, 2),
            "service_type_sales": service_type_sales,
            "in_progress_jobs":   in_progress_jobs,
            "ready_to_invoice":   ready_to_invoice,
        }, None

    except SQLAlchemyError as e:
        print(f"DB error get_jobs_dashboard_data: {e}")
        return None, ({"detail": "Database error.", "code": "db_error"}, 500)
    except Exception as e:
        print(f"Unexpected error get_jobs_dashboard_data: {e}")
        return None, ({"detail": "Unexpected server error.", "code": "internal_error"}, 500)


# ---------------------------------------------------------------------------
# Función para el endpoint del PDF
# ---------------------------------------------------------------------------

def get_jobs_status_metrics_data(job_type_raw: str | None, year_raw: str | None):
    """
    Backward-compatible wrapper used by the PDF report endpoint.
    Returns the same format as before (type, year, total, rows, unknown_status, null_status).
    """
    from sqlmodel import select
    from sqlalchemy import func
    from .metrics_shared import STATUS_CATALOG, _norm_job_type, _norm_year, _apply_year_filter

    job_type = _norm_job_type(job_type_raw)
    if job_type is None:
        return None, ({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}, 400)

    year = _norm_year(year_raw)
    if year_raw is not None and year is None:
        return None, ({"detail": "Invalid year. Use a valid number like 2025."}, 400)

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

        unknown_count = sum(counts_map.get(s, 0) for s in unknown_found)
        unknown_pct = (unknown_count / total * 100) if total else 0.0
        null_count = counts_map.get(None, 0)

        return {
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
        }, None

    except SQLAlchemyError as e:
        return None, ({"detail": "DB error.", "code": "db_error"}, 500)
