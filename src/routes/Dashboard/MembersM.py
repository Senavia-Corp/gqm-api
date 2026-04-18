from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy import func, and_, case, extract

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.ClientModel import Client
from src.models.MemberModel import Member
from src.models.link_models.JobMember import JobMemberLink
from src.models.link_models.ClientLinks import ClientMemberLink
from src.services.metrics.metrics_shared import (
    INPROGRESS_BY_TYPE,
    PAID_STATUSES,
    _norm_job_type,
    _norm_year,
)
from src.services.metrics.aux_func_metrics import (
    _safe_int, _type_expr, _year_expr, _sum_if,
)
from src.services.metrics.jobs_metrics_service import _money_expr, _safe_float


ACC_REP_ROLE = "Acc Rep Selling"

# Status QID que representa "Pending Vendor Quote"
PENDING_VENDOR_QUOTE_STATUS = "Assigned/P. Quote"

# All in-progress statuses across all types
INPROG_STATUSES = list(
    INPROGRESS_BY_TYPE["QID"]
    | INPROGRESS_BY_TYPE["PTL"]
    | INPROGRESS_BY_TYPE["PAR"]
)

PAID_STATUSES_LIST = list(PAID_STATUSES)


member_metrics_bp = Blueprint(
    "member_metrics_blueprint", __name__, url_prefix="/member_metrics"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sum_money_if(cond):
    """SUM(CASE WHEN cond THEN money_expr() ELSE 0.0 END) – dollars aggregation."""
    return func.coalesce(func.sum(case((cond, _money_expr()), else_=0.0)), 0.0)


def _avg_pct_if(cond):
    """
    AVG( CASE WHEN cond THEN pct_col ELSE NULL END )
    pct_col: QID -> Gqm_final_percentage, PTL/PAR -> Gqm_target_return.
    NULLs are ignored by AVG automatically.
    """
    pct_col = case(
        (Job.Job_type.in_(["PTL", "PAR"]), Job.Gqm_target_return),
        else_=Job.Gqm_final_percentage,
    )
    return func.avg(case((cond, pct_col), else_=None))


# =============================================================================
# ENDPOINT 1 — Summary list of members + financial KPIs
# GET /member_metrics/acc-rep-selling
# =============================================================================

@member_metrics_bp.get("/acc-rep-selling")
def members_acc_rep_selling_metrics():
    """
    GET /member_metrics/acc-rep-selling
        ?type=ALL|QID|PTL|PAR
        &year=2025
        &page=1
        &limit=25

    Per-member summary:
        total_quotes        – # total quotes
        total_quoted_usd    – $ quoted  (Gqm_target_sold_pricing for QID/PTL, same logic as money_expr for PAR)
        inprogress_count    – # in-progress jobs
        inprogress_usd      – $ in progress
        paid_count          – # paid jobs
        paid_usd            – $ paid
        avg_sale_per_job    – Ave $ Sale per Job  (paid_usd / paid_count)
        avg_target_sold_pct – Ave. target sold %
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    if job_type not in ("ALL", "QID", "PTL", "PAR"):
        return jsonify({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}), 400

    year = _norm_year(request.args.get("year"))
    if request.args.get("year") is not None and year is None:
        return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

    page  = max(_safe_int(request.args.get("page"),  1),   1)
    limit = min(max(_safe_int(request.args.get("limit"), 25), 1), 200)
    offset = (page - 1) * limit

    type_ok = _type_expr(job_type)
    year_ok = _year_expr(job_type, year)

    # Base condition: link exists + job exists + type/year filters
    base_cond = and_(
        JobMemberLink.member_id.is_not(None),
        Job.ID_Jobs.is_not(None),
        type_ok,
        year_ok,
    )

    inprog_cond = and_(base_cond, Job.Job_status.in_(INPROG_STATUSES))
    paid_cond   = and_(base_cond, Job.Job_status.in_(PAID_STATUSES_LIST))

    # ── Aggregated columns ──────────────────────────────────────────────────
    col_total_quotes        = _sum_if(base_cond).label("total_quotes")
    col_total_quoted_usd    = _sum_money_if(base_cond).label("total_quoted_usd")
    col_inprogress_count    = _sum_if(inprog_cond).label("inprogress_count")
    col_inprogress_usd      = _sum_money_if(inprog_cond).label("inprogress_usd")
    col_paid_count          = _sum_if(paid_cond).label("paid_count")
    col_paid_usd            = _sum_money_if(paid_cond).label("paid_usd")
    col_avg_target_sold_pct = _avg_pct_if(base_cond).label("avg_target_sold_pct")

    with get_session() as session:
        total_members = session.exec(
            select(func.count()).select_from(Member)
        ).one() or 0

        stmt = (
            select(
                Member.ID_Member,
                Member.Member_Name,
                Member.Company_Role,
                col_total_quotes,
                col_total_quoted_usd,
                col_inprogress_count,
                col_inprogress_usd,
                col_paid_count,
                col_paid_usd,
                col_avg_target_sold_pct,
            )
            .select_from(Member)
            .join(
                JobMemberLink,
                and_(
                    JobMemberLink.member_id == Member.ID_Member,
                    JobMemberLink.rol == ACC_REP_ROLE,
                ),
                isouter=True,
            )
            .join(Job, Job.ID_Jobs == JobMemberLink.job_id, isouter=True)
            .group_by(Member.ID_Member, Member.Member_Name, Member.Company_Role)
            .order_by(
                func.coalesce(col_paid_usd, 0).desc(),
                func.coalesce(col_total_quotes, 0).desc(),
                func.coalesce(Member.Member_Name, "").asc(),
            )
            .offset(offset)
            .limit(limit)
        )

        rows = session.exec(stmt).all()

    members = []
    for idx, r in enumerate(rows, start=1):
        paid_c = int(r.paid_count or 0)
        paid_u = _safe_float(r.paid_usd)
        avg_sale = round(paid_u / paid_c, 2) if paid_c else 0.0

        members.append({
            "rank": offset + idx,
            "member": {
                "id":           r.ID_Member,
                "name":         r.Member_Name,
                "company_role": r.Company_Role,
            },
            "summary": {
                "total_quotes":        int(r.total_quotes or 0),
                "total_quoted_usd":    round(_safe_float(r.total_quoted_usd), 2),
                "inprogress_count":    int(r.inprogress_count or 0),
                "inprogress_usd":      round(_safe_float(r.inprogress_usd), 2),
                "paid_count":          paid_c,
                "paid_usd":            round(paid_u, 2),
                "avg_sale_per_job":    avg_sale,
                "avg_target_sold_pct": round(_safe_float(r.avg_target_sold_pct), 4),
            },
        })

    total_pages = (int(total_members) + limit - 1) // limit if total_members else 1

    return jsonify({
        "type":        job_type,
        "year":        year,
        "role_filter": ACC_REP_ROLE,
        "pagination": {
            "page":          page,
            "limit":         limit,
            "total_members": int(total_members),
            "total_pages":   int(total_pages),
        },
        "members": members,
    }), 200


# =============================================================================
# ENDPOINT 2 — Individual stats per member
# GET /member_metrics/acc-rep-selling/<member_id>
# =============================================================================

@member_metrics_bp.get("/acc-rep-selling/<member_id>")
def member_individual_stats(member_id: str):
    """
    GET /member_metrics/acc-rep-selling/<member_id>
        ?year=2025

    Returns:
        member               – basic member info
        year_filter          – applied year filter (null = all years)
        communities_assigned – # of client communities assigned to this member
        pending_vendor_quotes – list of QIDs with status "Assigned/P. Quote"
                               [ { qid, date, client, description, status } ]
        qids_by_month        – QIDs grouped by month/year
                               [ { year, month, month_key, label, count, total_quoted_usd } ]
    """
    year = _norm_year(request.args.get("year"))
    if request.args.get("year") is not None and year is None:
        return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

    with get_session() as session:

        # ── 0. Member info ─────────────────────────────────────────────────
        member = session.exec(
            select(Member).where(Member.ID_Member == member_id)
        ).first()
        if not member:
            return jsonify({"detail": "Member not found."}), 404

        # ── 1. # of communities (clients) assigned ─────────────────────────
        communities_count = session.exec(
            select(func.count(ClientMemberLink.clients_id.distinct()))
            .where(ClientMemberLink.members_id == member_id)
        ).one() or 0

        # ── 2. Pending Vendor Quotes (QID / Assigned/P. Quote) ───────────
        pvq_stmt = (
            select(
                Job.ID_Jobs,
                Job.Date_assigned,
                Job.Date_Received,
                Job.Project_name,
                Job.Job_status,
                Client.Client_Community,
            )
            .join(
                JobMemberLink,
                and_(
                    JobMemberLink.job_id == Job.ID_Jobs,
                    JobMemberLink.member_id == member_id,
                    JobMemberLink.rol == ACC_REP_ROLE,
                ),
            )
            .outerjoin(Client, Client.ID_Client == Job.ID_Client)
            .where(
                Job.Job_type == "QID",
                Job.Job_status == PENDING_VENDOR_QUOTE_STATUS,
            )
            .order_by(
                func.coalesce(Job.Date_assigned, Job.Date_Received).asc().nullslast()
            )
        )

        if year is not None:
            pvq_stmt = pvq_stmt.where(
                and_(
                    Job.Date_assigned.is_not(None),
                    extract("year", Job.Date_assigned) == year,
                )
            )

        pending_vendor_quotes = []
        for row in session.exec(pvq_stmt).all():
            date_val = row.Date_assigned or row.Date_Received
            pending_vendor_quotes.append({
                "qid":         row.ID_Jobs,
                "date":        date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else None,
                "client":      row.Client_Community or "—",
                "description": row.Project_name or "—",
                "status":      row.Job_status or "—",
            })

        # ── 3. Financial summary (mirrors list endpoint per-member KPIs) ────
        type_ok_all = _type_expr("ALL")
        year_ok_all = _year_expr("ALL", year)
        sum_base = and_(
            JobMemberLink.member_id == member_id,
            JobMemberLink.rol == ACC_REP_ROLE,
            Job.ID_Jobs.is_not(None),
            type_ok_all,
            year_ok_all,
        )
        inprog_cond_d = and_(sum_base, Job.Job_status.in_(INPROG_STATUSES))
        paid_cond_d   = and_(sum_base, Job.Job_status.in_(PAID_STATUSES_LIST))

        summary_stmt = (
            select(
                _sum_if(sum_base).label("total_quotes"),
                func.coalesce(func.sum(case((sum_base, _money_expr()), else_=0.0)), 0.0).label("total_quoted_usd"),
                _sum_if(inprog_cond_d).label("inprogress_count"),
                func.coalesce(func.sum(case((inprog_cond_d, _money_expr()), else_=0.0)), 0.0).label("inprogress_usd"),
                _sum_if(paid_cond_d).label("paid_count"),
                func.coalesce(func.sum(case((paid_cond_d, _money_expr()), else_=0.0)), 0.0).label("paid_usd"),
                func.avg(case((sum_base, case(
                    (Job.Job_type.in_(["PTL", "PAR"]), Job.Gqm_target_return),
                    else_=Job.Gqm_final_percentage,
                )), else_=None)).label("avg_target_sold_pct"),
            )
            .select_from(JobMemberLink)
            .join(Job, Job.ID_Jobs == JobMemberLink.job_id, isouter=True)
        )
        s = session.exec(summary_stmt).first()
        paid_c = int(s.paid_count or 0) if s else 0
        paid_u = _safe_float(s.paid_usd) if s else 0.0
        summary = {
            "total_quotes":        int(s.total_quotes or 0) if s else 0,
            "total_quoted_usd":    round(_safe_float(s.total_quoted_usd) if s else 0.0, 2),
            "inprogress_count":    int(s.inprogress_count or 0) if s else 0,
            "inprogress_usd":      round(_safe_float(s.inprogress_usd) if s else 0.0, 2),
            "paid_count":          paid_c,
            "paid_usd":            round(paid_u, 2),
            "avg_sale_per_job":    round(paid_u / paid_c, 2) if paid_c else 0.0,
            "avg_target_sold_pct": round(_safe_float(s.avg_target_sold_pct) if s else 0.0, 4),
        }

        # ── 4. QIDs created per month / year ──────────────────────────────
        year_expr  = extract("year",  Job.Date_assigned)
        month_expr = extract("month", Job.Date_assigned)
        month_key  = func.to_char(Job.Date_assigned, "YYYY-MM")
        month_lbl  = func.to_char(Job.Date_assigned, "Month YYYY")

        qids_month_stmt = (
            select(
                year_expr.label("year"),
                month_expr.label("month"),
                month_key.label("month_key"),
                month_lbl.label("label"),
                func.count(Job.ID_Jobs).label("count"),
                func.sum(Job.Gqm_target_sold_pricing).label("total_quoted_usd"),
            )
            .join(
                JobMemberLink,
                and_(
                    JobMemberLink.job_id == Job.ID_Jobs,
                    JobMemberLink.member_id == member_id,
                    JobMemberLink.rol == ACC_REP_ROLE,
                ),
            )
            .where(
                Job.Job_type == "QID",
                Job.Date_assigned.is_not(None),
            )
            .group_by(year_expr, month_expr, month_key, month_lbl)
            .order_by(year_expr.desc(), month_expr.desc())
        )

        if year is not None:
            qids_month_stmt = qids_month_stmt.where(
                extract("year", Job.Date_assigned) == year
            )

        qids_by_month = []
        for row in session.exec(qids_month_stmt).all():
            qids_by_month.append({
                "year":             int(row.year or 0),
                "month":            int(row.month or 0),
                "month_key":        row.month_key or "—",
                "label":            (row.label or "—").strip(),
                "count":            int(row.count or 0),
                "total_quoted_usd": round(_safe_float(row.total_quoted_usd), 2),
            })

    return jsonify({
        "member": {
            "id":           member.ID_Member,
            "name":         member.Member_Name,
            "company_role": member.Company_Role,
            "email":        member.Email_Address,
        },
        "year_filter":           year,
        "communities_assigned":  int(communities_count),
        "summary":               summary,
        "pending_vendor_quotes": pending_vendor_quotes,
        "qids_by_month":         qids_by_month,
    }), 200
