from __future__ import annotations
from flask import Blueprint, jsonify, request
from src.services.metrics.jobs_metrics_service import get_jobs_dashboard_data
from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy import func, and_, literal
from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.MemberModel import Member
from src.models.link_models.JobMember import JobMemberLink
from src.services.metrics.jobs_metrics_service import get_jobs_dashboard_data
from src.services.metrics.metrics_shared import (
    PENDING_BY_TYPE,
    INPROGRESS_BY_TYPE,
    COMPLETED_BY_TYPE,
    CANCELLED_STATUS,
    CLOSED_BY_TYPE,
    STATUS_BREAKDOWN_LIST,
    _norm_job_type,
    _norm_year,
)
from src.services.metrics.aux_func_metrics import (
    _safe_int, _type_expr, _year_expr,
    _sum_if, _sum_money_if,
    _year_expr_any_job, _norm_order_by
)


ACC_REP_ROLE = "Acc Rep Selling"


job_metrics_bp = Blueprint("job_metrics_blueprint",
                           __name__, url_prefix="/jobs")


# =============================================================================
# ENDPOINT: Jobs Dashboard
# =============================================================================

@job_metrics_bp.get("/jobs/status")
def jobs_status_metrics():
    """
    GET /metrics/jobs/status?type=QID|PTL|PAR|ALL&year=2025
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
# ENDPOINT: Members metrics (Acc Rep Selling) + Pagination
# =============================================================================

@job_metrics_bp.get("/members/acc-rep-selling")
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
