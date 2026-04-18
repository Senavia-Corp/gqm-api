from flask import Blueprint, jsonify, request, Response
from sqlmodel import select
from sqlalchemy import func, extract, and_, or_, case, literal

from src.database.db_sqlmodel import get_session
from src.models.ClientModel import Client
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.models.JobModel import Job
from src.models.link_models.JobMember import JobMemberLink
from src.models.MemberModel import Member
from src.services.metrics.aux_func_metrics import (
    _safe_int, _type_expr, _year_expr, 
    _sum_if, _norm_order_by)
from src.services.metrics.metrics_shared import (
    PENDING_BY_TYPE,
    INPROGRESS_BY_TYPE,
    COMPLETED_BY_TYPE,
    CANCELLED_STATUS,
    CLOSED_BY_TYPE,
    STATUS_BREAKDOWN_LIST,
    _norm_job_type,
    _norm_year
)
from src.services.metrics.jobs_metrics_service import _money_expr


communities_bp = Blueprint("communities_blueprint", __name__, url_prefix="/communities")


# =============================================================================
# ENDPOINT: Dashboard de Clients 
# =============================================================================

@communities_bp.get("/clients")
def clients_metrics():
    """
    GET /communities/clients?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=25&order_by=closed|revenue&include_status_breakdown=1&search=
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    if job_type not in ("ALL", "QID", "PTL", "PAR"):
        return jsonify({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}), 400

    year = _norm_year(request.args.get("year"))
    if request.args.get("year") is not None and year is None:
        return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

    order_by = _norm_order_by(request.args.get("order_by"))
    search_q = (request.args.get("search") or "").strip() or None

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
    revenue_expr = _money_expr()

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
        if search_q:
            total_clients_stmt = total_clients_stmt.where(
                Client.Client_Community.ilike(f"%{search_q}%")
            )
        total_clients = session.exec(total_clients_stmt).one() or 0

        agg_base = (
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

                *status_cols,
            )
            .select_from(Client)
            .join(Job, Job.ID_Client == Client.ID_Client, isouter=True)
            .group_by(Client.ID_Client, Client.Client_Community, Client.Address)
        )
        if search_q:
            agg_base = agg_base.where(
                Client.Client_Community.ilike(f"%{search_q}%")
            )
        agg = agg_base.subquery("agg")

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
        "pagination": {
            "page": page,
            "limit": limit,
            "total_clients": int(total_clients),
            "total_pages": int(total_pages),
        },
        "clients": clients,
    }), 200



# =============================================================================
# ENDPOINT: Dashboard de Parent Mgm Co 
# =============================================================================

@communities_bp.get("/parent-mgmt-co")
def parent_mgmt_co_metrics():
    """
    GET /communities/parent-mgmt-co?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=25&order_by=closed|revenue&include_status_breakdown=1
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
    revenue_expr = _money_expr()

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
        rev_comm_col = func.coalesce(func.sum(case((is_closed, revenue_expr), else_=0.0)), 0.0)
        top_comm_stmt = select(
            Client.Client_Community.label("name"),
            total_jobs_col.label("total_jobs"),
            paid_jobs_col.label("paid_jobs"),
            rev_comm_col.label("revenue"),
        ).select_from(Client)\
         .join(Job, Job.ID_Client == Client.ID_Client, isouter=True)\
         .where(Client.ID_Community_Tracking == pmc_id, type_ok, year_ok)\
         .group_by(Client.ID_Client, Client.Client_Community)\
         .order_by(paid_jobs_col.desc(), total_jobs_col.desc(), Client.Client_Community.asc())\
         .limit(5)

        with get_session() as ds_session:
            tc_rows = ds_session.exec(top_comm_stmt).all()
            top_communities = [
                {
                    "name":       tc.name,
                    "total_jobs": int(tc.total_jobs or 0),
                    "paid_jobs":  int(tc.paid_jobs  or 0),
                    "revenue":    float(tc.revenue   or 0.0),
                }
                for tc in tc_rows
            ]

            # 2) Member Assignments subquery
            rev_col     = func.coalesce(func.sum(revenue_expr), 0.0)
            job_cnt_col = func.count(Job.ID_Jobs)
            member_assign_stmt = select(
                Client.Client_Community.label("community"),
                Member.Member_Name.label("member_name"),
                rev_col.label("revenue"),
                job_cnt_col.label("job_count"),
            ).select_from(Job)\
             .join(Client, Job.ID_Client == Client.ID_Client)\
             .join(JobMemberLink, Job.ID_Jobs == JobMemberLink.job_id)\
             .join(Member, JobMemberLink.member_id == Member.ID_Member)\
             .where(Client.ID_Community_Tracking == pmc_id, type_ok, year_ok)\
             .group_by(Client.Client_Community, Member.Member_Name)\
             .order_by(Client.Client_Community.asc(), rev_col.desc())

            ma_rows = ds_session.exec(member_assign_stmt).all()
            community_assignments = [
                {
                    "community":   ma.community,
                    "member_name": ma.member_name,
                    "revenue":     float(ma.revenue  or 0.0),
                    "job_count":   int(ma.job_count  or 0),
                }
                for ma in ma_rows
            ]


        item = {
            "rank_closed":  int(r.rank_closed),
            "rank_revenue": int(r.rank_revenue),

            "client": {
                "id":      r.pmc_id,
                "name":    r.pmc_name,
                "address": r.pmc_hq or "",
            },
            "communities_count": int(r.communities_count or 0),
            "dashboard_stats": {
                "total_amount_of_quotes": int(r.quotes_count    or 0),
                "dollars_quoted":         float(r.quotes_revenue or 0.0),
                "in_progress_jobs_count": int(r.inprog_all      or 0),
                "dollars_in_progress":    float(r.inprog_revenue or 0.0),
                "paid_jobs_count":        int(r.closed_all      or 0),
                "dollars_paid":           float(r.paid_revenue   or 0.0),
                "ave_target_sold_pct":    round(float(r.ave_target_sold or 0.0), 2),
            },
            "top_communities":      top_communities,
            "community_assignments": community_assignments,
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
        "type":     job_type,
        "year":     year,
        "order_by": order_by,
        "summary":  summary_data,
        # Top-level shape expected by the frontend
        "pagination": {
            "page":                 page,
            "limit":                limit,
            "total_parent_mgmt_cos": int(total_pmc),
            "total_pages":          int(total_pages),
        },
        "parent_mgmt_cos": pmcs,
    }), 200

    