from flask import Blueprint, jsonify, request, Response
from sqlmodel import select
from sqlalchemy import func, extract, and_, or_, case, literal
from sqlalchemy.exc import SQLAlchemyError

from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job
from ..models.MemberModel import Member
from ..models.link_models.JobMember import JobMemberLink
from ..models.ClientModel import Client
from ..models.ParentMgmtCoModel import ParentMgmtCo
from ..services.metrics.jobs_metrics_service import get_jobs_status_metrics_data, get_jobs_dashboard_data
from ..services.reports.jobs_report_pdf import build_jobs_report_pdf_bytes
from ..services.metrics.metrics_shared import (
    STATUS_CATALOG,
    PENDING_BY_TYPE,
    INPROGRESS_BY_TYPE,
    COMPLETED_BY_TYPE,
    CANCELLED_STATUS,
    CLOSED_BY_TYPE,
    STATUS_BREAKDOWN_LIST,
    _norm_job_type,
    _norm_year,
    _apply_year_filter,
)

metrics_bp = Blueprint("metrics_blueprint", __name__, url_prefix="/metrics")

ACC_REP_ROLE = "Acc Rep Selling"

# (Status buckets and normalizers imported from metrics_shared)


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


def _money_expr():
    """
    Revenue:
    - QID/PTL => Gqm_final_sold_pricing
    - PAR     => Gqm_target_sold_pricing
    """
    return case(
        (Job.Job_type == "PAR", func.coalesce(Job.Gqm_target_sold_pricing, 0.0)),
        else_=func.coalesce(Job.Gqm_final_sold_pricing, 0.0),
    )


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
# NEW ENDPOINT: Members Jobs
# =============================================================================


@metrics_bp.get("/jobs/status")
def jobs_status_metrics():
    """
    GET /metrics/jobs/status?type=QID|PTL|PAR|ALL&year=2025

    Returns the full Jobs Metrics Dashboard:
      - kpi_summary        : 8 KPI cards (total quoted, final sold, premium, avg %, # jobs, # paid, etc.)
      - monthly_sales      : Month-by-month breakdown (chart: paid jobs by date)
      - quarterly          : Quarter-by-quarter breakdown
      - rep_performance    : Sales performance by Acc Rep Selling / Mgmt Member
      - status_breakdown   : Distribution by job status + pipeline indicator
      - service_type_sales : Yearly sales grouped by service type (stacked bar data)
      - in_progress_jobs   : Listing of jobs currently In Progress with $ amount
      - ready_to_invoice   : Listing of jobs ready to be invoiced
      - pipeline           : Total $ in active (non-paid, non-cancelled) jobs
    """
    data, err = get_jobs_dashboard_data(
        request.args.get("type"),
        request.args.get("year"),
    )
    if err:
        payload, status_code = err
        return jsonify(payload), status_code

    return jsonify(data), 200


# =============================================================================
# NEW ENDPOINT: Members metrics (Acc Rep Selling) + Pagination
# =============================================================================

@metrics_bp.get("/members/acc-rep-selling")
def members_acc_rep_selling_metrics():
    """
    GET /metrics/members/acc-rep-selling?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=25&include_status_breakdown=1
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    if job_type not in ("ALL", "QID", "PTL", "PAR"):
        return jsonify({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}), 400

    year = _norm_year(request.args.get("year"))
    if request.args.get("year") is not None and year is None:
        return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

    page = _safe_int(request.args.get("page"), 1)
    limit = _safe_int(request.args.get("limit"), 25)
    page = max(page, 1)
    limit = min(max(limit, 1), 200)  # cap razonable
    offset = (page - 1) * limit

    include_status_breakdown = (request.args.get(
        "include_status_breakdown", "1").strip() != "0")

    type_ok = _type_expr(job_type)
    year_ok = _year_expr(job_type, year)

    # Solo cuenta cuando exista el vínculo Acc Rep Selling + job válido + pasa filtros
    base_cond = and_(
        JobMemberLink.member_id.is_not(None),
        Job.ID_Jobs.is_not(None),
        type_ok,
        year_ok,
    )

    def type_only(t: str):
        return and_(base_cond, Job.Job_type == t)

    def status_in(statuses: set[str]):
        return Job.Job_status.in_(list(statuses))

    # Totales
    total_all = _sum_if(base_cond).label("total_all")
    total_qid = _sum_if(type_only("QID")).label("total_qid")
    total_ptl = _sum_if(type_only("PTL")).label("total_ptl")
    total_par = _sum_if(type_only("PAR")).label("total_par")

    # Pending
    pending_qid = _sum_if(and_(type_only("QID"), status_in(
        PENDING_BY_TYPE["QID"]))).label("pending_qid")
    pending_ptl = _sum_if(and_(type_only("PTL"), status_in(
        PENDING_BY_TYPE["PTL"]))).label("pending_ptl")
    pending_par = literal(0).label("pending_par")
    pending_all = (func.coalesce(pending_qid, 0) +
                   func.coalesce(pending_ptl, 0)).label("pending_all")

    # In progress
    inprog_qid = _sum_if(and_(type_only("QID"), status_in(
        INPROGRESS_BY_TYPE["QID"]))).label("inprog_qid")
    inprog_ptl = _sum_if(and_(type_only("PTL"), status_in(
        INPROGRESS_BY_TYPE["PTL"]))).label("inprog_ptl")
    inprog_par = _sum_if(and_(type_only("PAR"), status_in(
        INPROGRESS_BY_TYPE["PAR"]))).label("inprog_par")
    inprog_all = (func.coalesce(inprog_qid, 0) + func.coalesce(inprog_ptl,
                  0) + func.coalesce(inprog_par, 0)).label("inprog_all")

    # Completed
    completed_qid = _sum_if(and_(type_only("QID"), status_in(
        COMPLETED_BY_TYPE["QID"]))).label("completed_qid")
    completed_ptl = _sum_if(and_(type_only("PTL"), status_in(
        COMPLETED_BY_TYPE["PTL"]))).label("completed_ptl")
    completed_par = _sum_if(and_(type_only("PAR"), status_in(
        COMPLETED_BY_TYPE["PAR"]))).label("completed_par")
    completed_all = (func.coalesce(completed_qid, 0) + func.coalesce(
        completed_ptl, 0) + func.coalesce(completed_par, 0)).label("completed_all")

    # Cancelled
    cancelled_all = _sum_if(
        and_(base_cond, Job.Job_status == CANCELLED_STATUS)).label("cancelled_all")
    cancelled_qid = _sum_if(and_(
        type_only("QID"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_qid")
    cancelled_ptl = _sum_if(and_(
        type_only("PTL"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_ptl")
    cancelled_par = _sum_if(and_(
        type_only("PAR"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_par")

    # Closed
    closed_qid = _sum_if(and_(type_only("QID"), status_in(
        CLOSED_BY_TYPE["QID"]))).label("closed_qid")
    closed_ptl = _sum_if(and_(type_only("PTL"), status_in(
        CLOSED_BY_TYPE["PTL"]))).label("closed_ptl")
    closed_par = _sum_if(and_(type_only("PAR"), status_in(
        CLOSED_BY_TYPE["PAR"]))).label("closed_par")
    closed_all = (func.coalesce(closed_qid, 0) + func.coalesce(closed_ptl,
                  0) + func.coalesce(closed_par, 0)).label("closed_all")

    # Breakdown por status (opcional)
    status_cols = []
    if include_status_breakdown:
        for s in STATUS_BREAKDOWN_LIST:
            status_cols.append(
                _sum_if(and_(base_cond, Job.Job_status == s)
                        ).label(f"st__{s}")
            )

    with get_session() as session:
        # total members (para paginación)
        total_members_stmt = select(func.count()).select_from(Member)
        total_members = session.exec(total_members_stmt).one() or 0

        stmt = (
            select(
                Member.ID_Member,
                Member.Member_Name,
                Member.Company_Role,

                total_all, total_qid, total_ptl, total_par,

                pending_all, inprog_all, completed_all, cancelled_all, closed_all,

                pending_qid, pending_ptl, pending_par,
                inprog_qid, inprog_ptl, inprog_par,
                completed_qid, completed_ptl, completed_par,
                cancelled_qid, cancelled_ptl, cancelled_par,
                closed_qid, closed_ptl, closed_par,

                *status_cols
            )
            .select_from(Member)
            # LEFT JOIN job_member con rol Acc Rep Selling (no rompe miembros sin jobs)
            .join(
                JobMemberLink,
                and_(
                    JobMemberLink.member_id == Member.ID_Member,
                    JobMemberLink.rol == ACC_REP_ROLE
                ),
                isouter=True
            )
            .join(
                Job,
                Job.ID_Jobs == JobMemberLink.job_id,
                isouter=True
            )
            .group_by(Member.ID_Member, Member.Member_Name, Member.Company_Role)
            .order_by(
                func.coalesce(closed_all, 0).desc(),
                func.coalesce(total_all, 0).desc(),
                func.coalesce(Member.Member_Name, "").asc(),
            )
            .offset(offset)
            .limit(limit)
        )

        rows = session.exec(stmt).all()

    # rank global aproximado: rank = offset + index
    # (si quieres rank EXACTO global con millones de filas, se hace con window function)
    members = []
    for idx, r in enumerate(rows, start=1):
        total_all_v = int(r.total_all or 0)
        completed_all_v = int(r.completed_all or 0)

        member_obj = {
            "rank": offset + idx,
            "member": {
                "id": r.ID_Member,
                "name": r.Member_Name,
                "company_role": r.Company_Role,
            },
            "totals": {
                "all": int(r.total_all or 0),
                "qid": int(r.total_qid or 0),
                "ptl": int(r.total_ptl or 0),
                "par": int(r.total_par or 0),
            },
            "buckets": {
                "pending": int(r.pending_all or 0),
                "in_progress": int(r.inprog_all or 0),
                "completed": int(r.completed_all or 0),
                "cancelled": int(r.cancelled_all or 0),
                "closed": int(r.closed_all or 0),
                "completed_pct": round((completed_all_v / total_all_v * 100.0), 2) if total_all_v else 0.0,
            },
            "bucket_by_type": {
                "qid": {
                    "pending": int(r.pending_qid or 0),
                    "in_progress": int(r.inprog_qid or 0),
                    "completed": int(r.completed_qid or 0),
                    "cancelled": int(r.cancelled_qid or 0),
                    "closed": int(r.closed_qid or 0),
                    "completed_pct": round((float(r.completed_qid or 0) / float(r.total_qid or 0) * 100.0), 2) if (r.total_qid or 0) else 0.0,
                },
                "ptl": {
                    "pending": int(r.pending_ptl or 0),
                    "in_progress": int(r.inprog_ptl or 0),
                    "completed": int(r.completed_ptl or 0),
                    "cancelled": int(r.cancelled_ptl or 0),
                    "closed": int(r.closed_ptl or 0),
                    "completed_pct": round((float(r.completed_ptl or 0) / float(r.total_ptl or 0) * 100.0), 2) if (r.total_ptl or 0) else 0.0,
                },
                "par": {
                    "pending": 0,
                    "in_progress": int(r.inprog_par or 0),
                    "completed": int(r.completed_par or 0),
                    "cancelled": int(r.cancelled_par or 0),
                    "closed": int(r.closed_par or 0),
                    "completed_pct": round((float(r.completed_par or 0) / float(r.total_par or 0) * 100.0), 2) if (r.total_par or 0) else 0.0,
                },
            }
        }

        if include_status_breakdown:
            breakdown = {}
            for s in STATUS_BREAKDOWN_LIST:
                breakdown[s] = int(getattr(r, f"st__{s}") or 0)
            member_obj["status_breakdown"] = breakdown

        members.append(member_obj)

    total_pages = (int(total_members) + limit -
                   1) // limit if total_members else 1

    return jsonify({
        "type": job_type,
        "year": year,
        "role_filter": ACC_REP_ROLE,
        "pagination": {
            "page": page,
            "limit": limit,
            "total_members": int(total_members),
            "total_pages": int(total_pages),
        },
        "members": members
    }), 200


# =============================================================================
# NEW ENDPOINT: Clients metrics
# =============================================================================

@metrics_bp.get("/clients")
def clients_metrics():
    """
    GET /metrics/clients?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=25&order_by=closed|revenue&include_status_breakdown=1
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    if job_type not in ("ALL", "QID", "PTL", "PAR"):
        return jsonify({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}), 400

    year = _norm_year(request.args.get("year"))
    if request.args.get("year") is not None and year is None:
        return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

    order_by = _norm_order_by(request.args.get("order_by"))

    page = _safe_int(request.args.get("page"), 1)
    limit = _safe_int(request.args.get("limit"), 25)
    page = max(page, 1)
    limit = min(max(limit, 1), 200)
    offset = (page - 1) * limit

    # ✅ NEW
    include_status_breakdown = (request.args.get(
        "include_status_breakdown", "0").strip() != "0")

    type_ok = _type_expr(job_type)
    year_ok = _year_expr(job_type, year)

    base_cond = and_(
        Job.ID_Jobs.is_not(None),
        Job.ID_Client.is_not(None),
        type_ok,
        year_ok,
    )

    def type_only(t: str):
        return and_(base_cond, Job.Job_type == t)

    def status_in(statuses: set[str]):
        return Job.Job_status.in_(list(statuses))

    # Totals
    total_all = _sum_if(base_cond).label("total_all")
    total_qid = _sum_if(type_only("QID")).label("total_qid")
    total_ptl = _sum_if(type_only("PTL")).label("total_ptl")
    total_par = _sum_if(type_only("PAR")).label("total_par")

    # Pending
    pending_qid = _sum_if(and_(type_only("QID"), status_in(
        PENDING_BY_TYPE["QID"]))).label("pending_qid")
    pending_ptl = _sum_if(and_(type_only("PTL"), status_in(
        PENDING_BY_TYPE["PTL"]))).label("pending_ptl")
    pending_par = literal(0).label("pending_par")
    pending_all = (func.coalesce(pending_qid, 0) +
                   func.coalesce(pending_ptl, 0)).label("pending_all")

    # In progress
    inprog_qid = _sum_if(and_(type_only("QID"), status_in(
        INPROGRESS_BY_TYPE["QID"]))).label("inprog_qid")
    inprog_ptl = _sum_if(and_(type_only("PTL"), status_in(
        INPROGRESS_BY_TYPE["PTL"]))).label("inprog_ptl")
    inprog_par = _sum_if(and_(type_only("PAR"), status_in(
        INPROGRESS_BY_TYPE["PAR"]))).label("inprog_par")
    inprog_all = (func.coalesce(inprog_qid, 0) + func.coalesce(inprog_ptl,
                  0) + func.coalesce(inprog_par, 0)).label("inprog_all")

    # Completed
    completed_qid = _sum_if(and_(type_only("QID"), status_in(
        COMPLETED_BY_TYPE["QID"]))).label("completed_qid")
    completed_ptl = _sum_if(and_(type_only("PTL"), status_in(
        COMPLETED_BY_TYPE["PTL"]))).label("completed_ptl")
    completed_par = _sum_if(and_(type_only("PAR"), status_in(
        COMPLETED_BY_TYPE["PAR"]))).label("completed_par")
    completed_all = (func.coalesce(completed_qid, 0) + func.coalesce(
        completed_ptl, 0) + func.coalesce(completed_par, 0)).label("completed_all")

    # Cancelled
    cancelled_all = _sum_if(
        and_(base_cond, Job.Job_status == CANCELLED_STATUS)).label("cancelled_all")
    cancelled_qid = _sum_if(and_(
        type_only("QID"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_qid")
    cancelled_ptl = _sum_if(and_(
        type_only("PTL"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_ptl")
    cancelled_par = _sum_if(and_(
        type_only("PAR"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_par")

    # Closed
    closed_qid = _sum_if(and_(type_only("QID"), status_in(
        CLOSED_BY_TYPE["QID"]))).label("closed_qid")
    closed_ptl = _sum_if(and_(type_only("PTL"), status_in(
        CLOSED_BY_TYPE["PTL"]))).label("closed_ptl")
    closed_par = _sum_if(and_(type_only("PAR"), status_in(
        CLOSED_BY_TYPE["PAR"]))).label("closed_par")
    closed_all = (func.coalesce(closed_qid, 0) + func.coalesce(closed_ptl,
                  0) + func.coalesce(closed_par, 0)).label("closed_all")

    # Revenue
    revenue_expr = case(
        (Job.Job_type == "PAR", func.coalesce(
            Job.Gqm_target_sold_pricing, 0.0)),
        else_=func.coalesce(Job.Gqm_final_sold_pricing, 0.0),
    )

    revenue_all = func.coalesce(
        func.sum(case((base_cond, revenue_expr), else_=0.0)),
        0.0
    ).label("revenue_all")

    revenue_qid = func.coalesce(
        func.sum(case((type_only("QID"), func.coalesce(
            Job.Gqm_final_sold_pricing, 0.0)), else_=0.0)),
        0.0
    ).label("revenue_qid")

    revenue_ptl = func.coalesce(
        func.sum(case((type_only("PTL"), func.coalesce(
            Job.Gqm_final_sold_pricing, 0.0)), else_=0.0)),
        0.0
    ).label("revenue_ptl")

    revenue_par = func.coalesce(
        func.sum(case((type_only("PAR"), func.coalesce(
            Job.Gqm_target_sold_pricing, 0.0)), else_=0.0)),
        0.0
    ).label("revenue_par")

    # ✅ NEW: dashboard summary metrics expressions
    def is_in_bucket_expr(bucket_dict):
        return or_(
            and_(Job.Job_type == "QID", status_in(bucket_dict.get("QID", set()))),
            and_(Job.Job_type == "PTL", status_in(bucket_dict.get("PTL", set()))),
            and_(Job.Job_type == "PAR", status_in(bucket_dict.get("PAR", set()))),
        )

    is_inprog = is_in_bucket_expr(INPROGRESS_BY_TYPE)
    is_closed = is_in_bucket_expr(CLOSED_BY_TYPE)

    quotes_count = _sum_if(and_(base_cond, Job.Job_status == "Assigned/P. Quote")).label("quotes_count")
    quotes_revenue = func.coalesce(func.sum(case((and_(base_cond, Job.Job_status == "Assigned/P. Quote"), revenue_expr), else_=0.0)), 0.0).label("quotes_revenue")
    inprog_revenue = func.coalesce(func.sum(case((and_(base_cond, is_inprog), revenue_expr), else_=0.0)), 0.0).label("inprog_revenue")
    paid_revenue = func.coalesce(func.sum(case((and_(base_cond, is_closed), revenue_expr), else_=0.0)), 0.0).label("paid_revenue")
    ave_target_sold = func.coalesce(func.avg(case((base_cond, Job.Gqm_target_return), else_=None)), 0.0).label("ave_target_sold")

    # ✅ NEW: status breakdown columns (safe labels)
    status_label_map = [(s, f"st_{i:02d}")
                        for i, s in enumerate(STATUS_BREAKDOWN_LIST)]
    status_cols = []
    if include_status_breakdown:
        for status, label in status_label_map:
            status_cols.append(
                _sum_if(and_(base_cond, Job.Job_status == status)
                        ).label(label)
            )

    with get_session() as session:
        # --- GLOBAL SUMMARY ---
        summary_stmt = select(
            func.coalesce(func.sum(case((and_(base_cond, Job.Job_status == "Assigned/P. Quote"), 1), else_=0)), 0).label("quotes_count"),
            func.coalesce(func.sum(case((and_(base_cond, Job.Job_status == "Assigned/P. Quote"), revenue_expr), else_=0.0)), 0.0).label("quotes_revenue"),
            func.coalesce(func.sum(case((and_(base_cond, is_inprog), 1), else_=0)), 0).label("inprog_count"),
            func.coalesce(func.sum(case((and_(base_cond, is_inprog), revenue_expr), else_=0.0)), 0.0).label("inprog_revenue"),
            func.coalesce(func.sum(case((and_(base_cond, is_closed), 1), else_=0)), 0).label("paid_count"),
            func.coalesce(func.sum(case((and_(base_cond, is_closed), revenue_expr), else_=0.0)), 0.0).label("paid_revenue"),
            func.coalesce(func.avg(case((base_cond, Job.Gqm_target_return), else_=None)), 0.0).label("ave_target_sold")
        ).select_from(Job)
        
        glob_summary = session.exec(summary_stmt).first()

        total_clients_stmt = select(func.count()).select_from(Client)
        total_clients = session.exec(total_clients_stmt).one() or 0

        agg = (
            select(
                Client.ID_Client.label("client_id"),
                Client.Client_Community.label("client_name"),
                Client.Address.label("client_address"),

                total_all, total_qid, total_ptl, total_par,

                pending_all, inprog_all, completed_all, cancelled_all, closed_all,
                pending_qid, pending_ptl, pending_par,
                inprog_qid, inprog_ptl, inprog_par,
                completed_qid, completed_ptl, completed_par,
                cancelled_qid, cancelled_ptl, cancelled_par,
                closed_qid, closed_ptl, closed_par,

                revenue_all, revenue_qid, revenue_ptl, revenue_par,
                
                quotes_count, quotes_revenue, inprog_revenue, paid_revenue, ave_target_sold,

                *status_cols,  # ✅ NEW
            )
            .select_from(Client)
            .join(Job, Job.ID_Client == Client.ID_Client, isouter=True)
            .group_by(Client.ID_Client, Client.Client_Community, Client.Address)
        ).subquery("agg")

        ranked = (
            select(
                agg,
                func.dense_rank().over(
                    order_by=(
                        func.coalesce(agg.c.closed_all, 0).desc(),
                        func.coalesce(agg.c.total_all, 0).desc(),
                        func.coalesce(agg.c.client_name, "").asc(),
                    )
                ).label("rank_closed"),
                func.dense_rank().over(
                    order_by=(
                        func.coalesce(agg.c.revenue_all, 0.0).desc(),
                        func.coalesce(agg.c.closed_all, 0).desc(),
                        func.coalesce(agg.c.client_name, "").asc(),
                    )
                ).label("rank_revenue"),
            )
        )

        if order_by == "revenue":
            ranked = ranked.order_by(
                func.coalesce(agg.c.revenue_all, 0.0).desc(),
                func.coalesce(agg.c.closed_all, 0).desc(),
                func.coalesce(agg.c.total_all, 0).desc(),
                func.coalesce(agg.c.client_name, "").asc(),
            )
        else:
            ranked = ranked.order_by(
                func.coalesce(agg.c.closed_all, 0).desc(),
                func.coalesce(agg.c.total_all, 0).desc(),
                func.coalesce(agg.c.revenue_all, 0.0).desc(),
                func.coalesce(agg.c.client_name, "").asc(),
            )

        ranked = ranked.offset(offset).limit(limit)
        rows = session.exec(ranked).all()

    clients = []
    for r in rows:
        total_all_v = int(r.total_all or 0)
        completed_all_v = int(r.completed_all or 0)

        item = {
            "rank_closed": int(r.rank_closed),
            "rank_revenue": int(r.rank_revenue),
            "client": {"id": r.client_id, "name": r.client_name, "address": r.client_address},
            "dashboard_stats": {
                "total_amount_of_quotes": int(r.quotes_count or 0),
                "dollars_quoted": float(r.quotes_revenue or 0.0),
                "in_progress_jobs_count": int(r.inprog_all or 0),
                "dollars_in_progress": float(r.inprog_revenue or 0.0),
                "paid_jobs_count": int(r.closed_all or 0),
                "dollars_paid": float(r.paid_revenue or 0.0),
                "ave_target_sold_pct": round(float(r.ave_target_sold or 0.0), 2)
            },
            "totals": {
                "all": int(r.total_all or 0),
                "qid": int(r.total_qid or 0),
                "ptl": int(r.total_ptl or 0),
                "par": int(r.total_par or 0),
            },
            "buckets": {
                "pending": int(r.pending_all or 0),
                "in_progress": int(r.inprog_all or 0),
                "completed": int(r.completed_all or 0),
                "cancelled": int(r.cancelled_all or 0),
                "closed": int(r.closed_all or 0),
                "completed_pct": round((completed_all_v / total_all_v * 100.0), 2) if total_all_v else 0.0,
            },
            "bucket_by_type": {
                "qid": {
                    "pending": int(r.pending_qid or 0),
                    "in_progress": int(r.inprog_qid or 0),
                    "completed": int(r.completed_qid or 0),
                    "cancelled": int(r.cancelled_qid or 0),
                    "closed": int(r.closed_qid or 0),
                    "completed_pct": round((float(r.completed_qid or 0) / float(r.total_qid or 0) * 100.0), 2)
                    if (r.total_qid or 0) else 0.0,
                },
                "ptl": {
                    "pending": int(r.pending_ptl or 0),
                    "in_progress": int(r.inprog_ptl or 0),
                    "completed": int(r.completed_ptl or 0),
                    "cancelled": int(r.cancelled_ptl or 0),
                    "closed": int(r.closed_ptl or 0),
                    "completed_pct": round((float(r.completed_ptl or 0) / float(r.total_ptl or 0) * 100.0), 2)
                    if (r.total_ptl or 0) else 0.0,
                },
                "par": {
                    "pending": 0,
                    "in_progress": int(r.inprog_par or 0),
                    "completed": int(r.completed_par or 0),
                    "cancelled": int(r.cancelled_par or 0),
                    "closed": int(r.closed_par or 0),
                    "completed_pct": round((float(r.completed_par or 0) / float(r.total_par or 0) * 100.0), 2)
                    if (r.total_par or 0) else 0.0,
                },
            },
            "revenue": {
                "all": float(r.revenue_all or 0.0),
                "qid": float(r.revenue_qid or 0.0),
                "ptl": float(r.revenue_ptl or 0.0),
                "par": float(r.revenue_par or 0.0),
            },
        }

        # ✅ NEW: attach breakdown
        if include_status_breakdown:
            breakdown = {}
            m = r._mapping
            for status, label in status_label_map:
                breakdown[status] = int(m.get(label) or 0)
            item["status_breakdown"] = breakdown

        clients.append(item)

    total_pages = (int(total_clients) + limit -
                   1) // limit if total_clients else 1

    # Format the global summary
    global_s = glob_summary._mapping if glob_summary else {}
    summary_data = {
        "total_amount_of_quotes": int(global_s.get("quotes_count", 0)),
        "dollars_quoted": float(global_s.get("quotes_revenue", 0.0)),
        "in_progress_jobs_count": int(global_s.get("inprog_count", 0)),
        "dollars_in_progress": float(global_s.get("inprog_revenue", 0.0)),
        "paid_jobs_count": int(global_s.get("paid_count", 0)),
        "dollars_paid": float(global_s.get("paid_revenue", 0.0)),
        "ave_target_sold_pct": round(float(global_s.get("ave_target_sold", 0.0)), 2)
    }

    return jsonify({
        "type": job_type,
        "year": year,
        "order_by": order_by,
        "include_status_breakdown": 1 if include_status_breakdown else 0,
        "summary": summary_data,
        "individual_stats": {
            "total_clients": int(total_clients),
            "pagination": {
                "page": page,
                "limit": limit,
                "total_pages": int(total_pages),
            },
            "top_clients": clients
        }
    }), 200

# =============================================================================
# NEW ENDPOINT: Parent Management Co
# =============================================================================


@metrics_bp.get("/parent-mgmt-co")
def parent_mgmt_co_metrics():
    """
    GET /metrics/parent-mgmt-co?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=25&order_by=closed|revenue&include_status_breakdown=1
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    if job_type not in ("ALL", "QID", "PTL", "PAR"):
        return jsonify({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}), 400

    year = _norm_year(request.args.get("year"))
    if request.args.get("year") is not None and year is None:
        return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

    order_by = _norm_order_by(request.args.get("order_by"))

    page = _safe_int(request.args.get("page"), 1)
    limit = _safe_int(request.args.get("limit"), 25)
    page = max(page, 1)
    limit = min(max(limit, 1), 200)
    offset = (page - 1) * limit

    # ✅ NEW
    include_status_breakdown = (request.args.get(
        "include_status_breakdown", "0").strip() != "0")

    type_ok = _type_expr(job_type)
    year_ok = _year_expr(job_type, year)

    # Jobs válidos: linkeados a un client que linkea a un parent mgmt co
    base_cond = and_(
        Job.ID_Jobs.is_not(None),
        Job.ID_Client.is_not(None),
        Client.ID_Community_Tracking.is_not(None),
        type_ok,
        year_ok,
    )

    def type_only(t: str):
        return and_(base_cond, Job.Job_type == t)

    def status_in(statuses: set[str]):
        return Job.Job_status.in_(list(statuses))

    # Totals
    total_all = _sum_if(base_cond).label("total_all")
    total_qid = _sum_if(type_only("QID")).label("total_qid")
    total_ptl = _sum_if(type_only("PTL")).label("total_ptl")
    total_par = _sum_if(type_only("PAR")).label("total_par")

    # Pending
    pending_qid = _sum_if(and_(type_only("QID"), status_in(
        PENDING_BY_TYPE["QID"]))).label("pending_qid")
    pending_ptl = _sum_if(and_(type_only("PTL"), status_in(
        PENDING_BY_TYPE["PTL"]))).label("pending_ptl")
    pending_par = literal(0).label("pending_par")
    pending_all = (func.coalesce(pending_qid, 0) +
                   func.coalesce(pending_ptl, 0)).label("pending_all")

    # In progress
    inprog_qid = _sum_if(and_(type_only("QID"), status_in(
        INPROGRESS_BY_TYPE["QID"]))).label("inprog_qid")
    inprog_ptl = _sum_if(and_(type_only("PTL"), status_in(
        INPROGRESS_BY_TYPE["PTL"]))).label("inprog_ptl")
    inprog_par = _sum_if(and_(type_only("PAR"), status_in(
        INPROGRESS_BY_TYPE["PAR"]))).label("inprog_par")
    inprog_all = (func.coalesce(inprog_qid, 0) + func.coalesce(inprog_ptl,
                  0) + func.coalesce(inprog_par, 0)).label("inprog_all")

    # Completed
    completed_qid = _sum_if(and_(type_only("QID"), status_in(
        COMPLETED_BY_TYPE["QID"]))).label("completed_qid")
    completed_ptl = _sum_if(and_(type_only("PTL"), status_in(
        COMPLETED_BY_TYPE["PTL"]))).label("completed_ptl")
    completed_par = _sum_if(and_(type_only("PAR"), status_in(
        COMPLETED_BY_TYPE["PAR"]))).label("completed_par")
    completed_all = (func.coalesce(completed_qid, 0) + func.coalesce(
        completed_ptl, 0) + func.coalesce(completed_par, 0)).label("completed_all")

    # Cancelled
    cancelled_all = _sum_if(
        and_(base_cond, Job.Job_status == CANCELLED_STATUS)).label("cancelled_all")
    cancelled_qid = _sum_if(and_(
        type_only("QID"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_qid")
    cancelled_ptl = _sum_if(and_(
        type_only("PTL"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_ptl")
    cancelled_par = _sum_if(and_(
        type_only("PAR"), Job.Job_status == CANCELLED_STATUS)).label("cancelled_par")

    # Closed
    closed_qid = _sum_if(and_(type_only("QID"), status_in(
        CLOSED_BY_TYPE["QID"]))).label("closed_qid")
    closed_ptl = _sum_if(and_(type_only("PTL"), status_in(
        CLOSED_BY_TYPE["PTL"]))).label("closed_ptl")
    closed_par = _sum_if(and_(type_only("PAR"), status_in(
        CLOSED_BY_TYPE["PAR"]))).label("closed_par")
    closed_all = (func.coalesce(closed_qid, 0) + func.coalesce(closed_ptl,
                  0) + func.coalesce(closed_par, 0)).label("closed_all")

    # Revenue (QID/PTL -> final, PAR -> target)
    revenue_expr = case(
        (Job.Job_type == "PAR", func.coalesce(
            Job.Gqm_target_sold_pricing, 0.0)),
        else_=func.coalesce(Job.Gqm_final_sold_pricing, 0.0),
    )

    revenue_all = func.coalesce(
        func.sum(case((base_cond, revenue_expr), else_=0.0)),
        0.0
    ).label("revenue_all")

    revenue_qid = func.coalesce(
        func.sum(case((type_only("QID"), func.coalesce(
            Job.Gqm_final_sold_pricing, 0.0)), else_=0.0)),
        0.0
    ).label("revenue_qid")

    revenue_ptl = func.coalesce(
        func.sum(case((type_only("PTL"), func.coalesce(
            Job.Gqm_final_sold_pricing, 0.0)), else_=0.0)),
        0.0
    ).label("revenue_ptl")

    revenue_par = func.coalesce(
        func.sum(case((type_only("PAR"), func.coalesce(
            Job.Gqm_target_sold_pricing, 0.0)), else_=0.0)),
        0.0
    ).label("revenue_par")

    # ✅ NEW: dashboard summary metrics expressions
    def is_in_bucket_expr(bucket_dict):
        return or_(
            and_(Job.Job_type == "QID", status_in(bucket_dict.get("QID", set()))),
            and_(Job.Job_type == "PTL", status_in(bucket_dict.get("PTL", set()))),
            and_(Job.Job_type == "PAR", status_in(bucket_dict.get("PAR", set()))),
        )

    is_inprog = is_in_bucket_expr(INPROGRESS_BY_TYPE)
    is_closed = is_in_bucket_expr(CLOSED_BY_TYPE)

    quotes_count = _sum_if(and_(base_cond, Job.Job_status == "Assigned/P. Quote")).label("quotes_count")
    quotes_revenue = func.coalesce(func.sum(case((and_(base_cond, Job.Job_status == "Assigned/P. Quote"), revenue_expr), else_=0.0)), 0.0).label("quotes_revenue")
    inprog_revenue = func.coalesce(func.sum(case((and_(base_cond, is_inprog), revenue_expr), else_=0.0)), 0.0).label("inprog_revenue")
    paid_revenue = func.coalesce(func.sum(case((and_(base_cond, is_closed), revenue_expr), else_=0.0)), 0.0).label("paid_revenue")
    ave_target_sold = func.coalesce(func.avg(case((base_cond, Job.Gqm_target_return), else_=None)), 0.0).label("ave_target_sold")
    
    # ✅ Count of distinct communities per parent co
    communities_count = func.count(func.distinct(Client.ID_Client)).label("communities_count")

    # ✅ NEW: status breakdown columns (safe labels)
    status_label_map = [(s, f"st_{i:02d}")
                        for i, s in enumerate(STATUS_BREAKDOWN_LIST)]
    status_cols = []
    if include_status_breakdown:
        for status, label in status_label_map:
            status_cols.append(
                _sum_if(and_(base_cond, Job.Job_status == status)
                        ).label(label)
            )

    with get_session() as session:
        # --- GLOBAL SUMMARY ---
        summary_stmt = select(
            func.coalesce(func.sum(case((and_(base_cond, Job.Job_status == "Assigned/P. Quote"), 1), else_=0)), 0).label("quotes_count"),
            func.coalesce(func.sum(case((and_(base_cond, Job.Job_status == "Assigned/P. Quote"), revenue_expr), else_=0.0)), 0.0).label("quotes_revenue"),
            func.coalesce(func.sum(case((and_(base_cond, is_inprog), 1), else_=0)), 0).label("inprog_count"),
            func.coalesce(func.sum(case((and_(base_cond, is_inprog), revenue_expr), else_=0.0)), 0.0).label("inprog_revenue"),
            func.coalesce(func.sum(case((and_(base_cond, is_closed), 1), else_=0)), 0).label("paid_count"),
            func.coalesce(func.sum(case((and_(base_cond, is_closed), revenue_expr), else_=0.0)), 0.0).label("paid_revenue"),
            func.coalesce(func.avg(case((base_cond, Job.Gqm_target_return), else_=None)), 0.0).label("ave_target_sold")
        ).select_from(Job).join(Client, Job.ID_Client == Client.ID_Client, isouter=True)
        
        glob_summary = session.exec(summary_stmt).first()

        total_pmc_stmt = select(func.count()).select_from(ParentMgmtCo)
        total_pmc = session.exec(total_pmc_stmt).one() or 0

        # 1) Aggregation per Parent Mgmt Co (via Client)
        agg = (
            select(
                ParentMgmtCo.ID_Community_Tracking.label("pmc_id"),
                ParentMgmtCo.Property_mgmt_co.label("pmc_name"),
                ParentMgmtCo.Main_office_hq.label("pmc_hq"),

                total_all, total_qid, total_ptl, total_par,

                pending_all, inprog_all, completed_all, cancelled_all, closed_all,
                pending_qid, pending_ptl, pending_par,
                inprog_qid, inprog_ptl, inprog_par,
                completed_qid, completed_ptl, completed_par,
                cancelled_qid, cancelled_ptl, cancelled_par,
                closed_qid, closed_ptl, closed_par,

                revenue_all, revenue_qid, revenue_ptl, revenue_par,
                
                quotes_count, quotes_revenue, inprog_revenue, paid_revenue, ave_target_sold,
                communities_count,

                *status_cols,  # ✅ NEW
            )
            .select_from(ParentMgmtCo)
            .join(Client, Client.ID_Community_Tracking == ParentMgmtCo.ID_Community_Tracking, isouter=True)
            .join(Job, Job.ID_Client == Client.ID_Client, isouter=True)
            .group_by(ParentMgmtCo.ID_Community_Tracking, ParentMgmtCo.Property_mgmt_co, ParentMgmtCo.Main_office_hq)
        ).subquery("agg")

        # 2) Add both ranks
        ranked = (
            select(
                agg,
                func.dense_rank().over(
                    order_by=(
                        func.coalesce(agg.c.closed_all, 0).desc(),
                        func.coalesce(agg.c.total_all, 0).desc(),
                        func.coalesce(agg.c.pmc_name, "").asc(),
                    )
                ).label("rank_closed"),
                func.dense_rank().over(
                    order_by=(
                        func.coalesce(agg.c.revenue_all, 0.0).desc(),
                        func.coalesce(agg.c.closed_all, 0).desc(),
                        func.coalesce(agg.c.pmc_name, "").asc(),
                    )
                ).label("rank_revenue"),
            )
        )

        # 3) Sort list
        if order_by == "revenue":
            ranked = ranked.order_by(
                func.coalesce(agg.c.revenue_all, 0.0).desc(),
                func.coalesce(agg.c.closed_all, 0).desc(),
                func.coalesce(agg.c.total_all, 0).desc(),
                func.coalesce(agg.c.pmc_name, "").asc(),
            )
        else:
            ranked = ranked.order_by(
                func.coalesce(agg.c.closed_all, 0).desc(),
                func.coalesce(agg.c.total_all, 0).desc(),
                func.coalesce(agg.c.revenue_all, 0.0).desc(),
                func.coalesce(agg.c.pmc_name, "").asc(),
            )

        ranked = ranked.offset(offset).limit(limit)

        rows = session.exec(ranked).all()

    pmcs = []
    for r in rows:
        pmc_id = r.pmc_id
        total_all_v = int(r.total_all or 0)
        completed_all_v = int(r.completed_all or 0)

        # 1) Top Communities subquery
        paid_jobs_col = func.sum(case((is_closed, 1), else_=0))
        total_jobs_col = func.count(Job.ID_Jobs)
        top_comm_stmt = select(
            Client.ID_Client.label("client_id"),
            Client.Client_Community.label("name"),
            total_jobs_col.label("total_jobs"),
            paid_jobs_col.label("paid_jobs")
        ).select_from(Client)\
         .join(Job, Job.ID_Client == Client.ID_Client, isouter=True)\
         .where(Client.ID_Community_Tracking == pmc_id, type_ok, year_ok)\
         .group_by(Client.ID_Client, Client.Client_Community)\
         .order_by(paid_jobs_col.desc(), total_jobs_col.desc(), Client.Client_Community.asc())\
         .limit(5)
         
        with get_session() as ds_session:
            tc_rows = ds_session.exec(top_comm_stmt).all()
            top_communities = [{"id": tc.client_id, "name": tc.name, "total_jobs": tc.total_jobs or 0, "paid_jobs": tc.paid_jobs or 0} for tc in tc_rows]

            # 2) Member Assignments subquery
            rev_col = func.sum(revenue_expr)
            member_assign_stmt = select(
                Client.Client_Community.label("community_name"),
                Member.Member_Name.label("member_name"),
                rev_col.label("revenue")
            ).select_from(Job)\
             .join(Client, Job.ID_Client == Client.ID_Client)\
             .join(JobMemberLink, Job.ID_Jobs == JobMemberLink.job_id)\
             .join(Member, JobMemberLink.member_id == Member.ID_Member)\
             .where(Client.ID_Community_Tracking == pmc_id, type_ok, year_ok)\
             .group_by(Client.Client_Community, Member.Member_Name)\
             .order_by(rev_col.desc())\
             .limit(10)
             
            ma_rows = ds_session.exec(member_assign_stmt).all()
            member_assignments = [{"community_name": ma.community_name, "member_name": ma.member_name, "revenue": float(ma.revenue or 0.0)} for ma in ma_rows]


        item = {
            "rank_closed": int(r.rank_closed),
            "rank_revenue": int(r.rank_revenue),

            "parent_mgmt_co": {
                "id": r.pmc_id,
                "name": r.pmc_name,
                "hq": r.pmc_hq,
            },
            "dashboard_stats": {
                "total_amount_of_quotes": int(r.quotes_count or 0),
                "dollars_quoted": float(r.quotes_revenue or 0.0),
                "in_progress_jobs_count": int(r.inprog_all or 0),
                "dollars_in_progress": float(r.inprog_revenue or 0.0),
                "paid_jobs_count": int(r.closed_all or 0),
                "dollars_paid": float(r.paid_revenue or 0.0),
                "ave_target_sold_pct": round(float(r.ave_target_sold or 0.0), 2),
                "communities_count": int(r.communities_count or 0)
            },
            "top_communities": top_communities,
            "community_assignments": member_assignments,
            "totals": {
                "all": int(r.total_all or 0),
                "qid": int(r.total_qid or 0),
                "ptl": int(r.total_ptl or 0),
                "par": int(r.total_par or 0),
            },
            "buckets": {
                "pending": int(r.pending_all or 0),
                "in_progress": int(r.inprog_all or 0),
                "completed": int(r.completed_all or 0),
                "cancelled": int(r.cancelled_all or 0),
                "closed": int(r.closed_all or 0),
                "completed_pct": round((completed_all_v / total_all_v * 100.0), 2) if total_all_v else 0.0,
            },
            "bucket_by_type": {
                "qid": {
                    "pending": int(r.pending_qid or 0),
                    "in_progress": int(r.inprog_qid or 0),
                    "completed": int(r.completed_qid or 0),
                    "cancelled": int(r.cancelled_qid or 0),
                    "closed": int(r.closed_qid or 0),
                    "completed_pct": round((float(r.completed_qid or 0) / float(r.total_qid or 0) * 100.0), 2)
                    if (r.total_qid or 0) else 0.0,
                },
                "ptl": {
                    "pending": int(r.pending_ptl or 0),
                    "in_progress": int(r.inprog_ptl or 0),
                    "completed": int(r.completed_ptl or 0),
                    "cancelled": int(r.cancelled_ptl or 0),
                    "closed": int(r.closed_ptl or 0),
                    "completed_pct": round((float(r.completed_ptl or 0) / float(r.total_ptl or 0) * 100.0), 2)
                    if (r.total_ptl or 0) else 0.0,
                },
                "par": {
                    "pending": 0,
                    "in_progress": int(r.inprog_par or 0),
                    "completed": int(r.completed_par or 0),
                    "cancelled": int(r.cancelled_par or 0),
                    "closed": int(r.closed_par or 0),
                    "completed_pct": round((float(r.completed_par or 0) / float(r.total_par or 0) * 100.0), 2)
                    if (r.total_par or 0) else 0.0,
                },
            },
            "revenue": {
                "all": float(r.revenue_all or 0.0),
                "qid": float(r.revenue_qid or 0.0),
                "ptl": float(r.revenue_ptl or 0.0),
                "par": float(r.revenue_par or 0.0),
            }
        }

        # ✅ NEW: attach breakdown
        if include_status_breakdown:
            breakdown = {}
            m = r._mapping
            for status, label in status_label_map:
                breakdown[status] = int(m.get(label) or 0)
            item["status_breakdown"] = breakdown

        pmcs.append(item)

    total_pages = (int(total_pmc) + limit - 1) // limit if total_pmc else 1

    # Format the global summary
    global_s = glob_summary._mapping if glob_summary else {}
    summary_data = {
        "total_amount_of_quotes": int(global_s.get("quotes_count", 0)),
        "dollars_quoted": float(global_s.get("quotes_revenue", 0.0)),
        "in_progress_jobs_count": int(global_s.get("inprog_count", 0)),
        "dollars_in_progress": float(global_s.get("inprog_revenue", 0.0)),
        "paid_jobs_count": int(global_s.get("paid_count", 0)),
        "dollars_paid": float(global_s.get("paid_revenue", 0.0)),
        "ave_target_sold_pct": round(float(global_s.get("ave_target_sold", 0.0)), 2)
    }

    return jsonify({
        "type": job_type,
        "year": year,
        "order_by": order_by,
        # opcional, útil para debug
        "include_status_breakdown": 1 if include_status_breakdown else 0,
        "summary": summary_data,
        "individual_stats": {
            "pagination": {
                "page": page,
                "limit": limit,
                "total_parent_mgmt_cos": int(total_pmc),
                "total_pages": int(total_pages),
            },
            "parent_mgmt_cos": pmcs
        }
    }), 200


# =============================================================================
# NEW ENDPOINT: Reportes de Jobs
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
