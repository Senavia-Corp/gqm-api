from __future__ import annotations
from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy import func
from src.models.ClientModel import Client
from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.MemberModel import Member
from src.models.link_models.JobMember import JobMemberLink
from src.services.metrics.jobs_metrics_service import get_jobs_dashboard_data
from src.services.metrics.metrics_shared import (
    _norm_job_type,
    _norm_year,
)
from src.services.metrics.aux_func_metrics import _safe_int, _year_expr
from sqlalchemy import and_


job_metrics_bp = Blueprint("job_metrics_blueprint",
                           __name__, url_prefix="/job_metrics")


# =============================================================================
# ENDPOINT: Jobs Dashboard
# =============================================================================

@job_metrics_bp.get("/status")
def jobs_status_metrics():
    """
    GET /job_metrics/status?type=QID|PTL|PAR|ALL&year=2025
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
# ENDPOINT: Jobs Member Pipeline (Active jobs by Member)
# =============================================================================

@job_metrics_bp.get("/member-pipeline")
def jobs_member_pipeline():
    """
    GET /job_metrics/member-pipeline?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=10
    List members and their active jobs (P/Quote for QID, In Progress for PAR/PTL)
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    year = _norm_year(request.args.get("year"))

    page = _safe_int(request.args.get("page"), 1)
    limit = _safe_int(request.args.get("limit"), 10)
    offset = (max(page, 1) - 1) * limit

    # Define active statuses specifically for this "Pipeline" view
    # QID: Assigned/P. Quote
    # PAR: In Progress
    # PTL: Assigned-In progress (User said schedule/work in progress (PTL))
    pipe_map = {
        "QID": ["Assigned/P. Quote"],
        "PTL": ["Assigned-In progress"],
        "PAR": ["In Progress"]
    }

    if job_type == "ALL":
        target_statuses = pipe_map["QID"] + pipe_map["PTL"] + pipe_map["PAR"]
        roles_to_use = ["Acc Rep Selling", "Mgmt Member"]
    else:
        target_statuses = pipe_map.get(job_type, [])
        roles_to_use = ["Mgmt Member"] if job_type == "PTL" else [
            "Acc Rep Selling"]

    with get_session() as session:
        # 1. Count total members who have jobs in these statuses
        # (Or just total members in general if we want a full list)
        # The user said "Jobs de cada miembro que están en...", implying we should list members.

        base_stmt = (
            select(Member)
            .join(JobMemberLink, JobMemberLink.member_id == Member.ID_Member)
            .join(Job, Job.ID_Jobs == JobMemberLink.job_id)
            .where(
                JobMemberLink.rol.in_(roles_to_use),
                Job.Job_status.in_(target_statuses)
            )
        )
        if job_type != "ALL":
            base_stmt = base_stmt.where(Job.Job_type == job_type)
        if year:
            from src.services.metrics.metrics_shared import _apply_year_filter
            base_stmt = _apply_year_filter(base_stmt, job_type, year)

        total_members_stmt = select(func.count(func.distinct(
            Member.ID_Member))).select_from(base_stmt.subquery())
        total_members = session.exec(total_members_stmt).one() or 0

        # 2. Get members for the current page
        members_stmt = (
            select(Member)
            .distinct()
            .join(JobMemberLink, JobMemberLink.member_id == Member.ID_Member)
            .join(Job, Job.ID_Jobs == JobMemberLink.job_id)
            .where(
                JobMemberLink.rol.in_(roles_to_use),
                Job.Job_status.in_(target_statuses)
            )
            .order_by(Member.Member_Name)
            .offset(offset)
            .limit(limit)
        )
        if job_type != "ALL":
            members_stmt = members_stmt.where(Job.Job_type == job_type)
        if year:
            members_stmt = _apply_year_filter(members_stmt, job_type, year)

        members_list = session.exec(members_stmt).all()
        member_ids = [m.ID_Member for m in members_list]

        # 3. Get all jobs for these members in a single query
        jobs_data = []
        if member_ids:
            jobs_stmt = (
                select(Job, JobMemberLink.member_id, Client)
                .outerjoin(Client, Client.ID_Client == Job.ID_Client)
                .join(JobMemberLink, JobMemberLink.job_id == Job.ID_Jobs)
                .where(
                    JobMemberLink.member_id.in_(member_ids),
                    JobMemberLink.rol.in_(roles_to_use),
                    Job.Job_status.in_(target_statuses)
                )
            )
            if job_type != "ALL":
                jobs_stmt = jobs_stmt.where(Job.Job_type == job_type)
            if year:
                jobs_stmt = _apply_year_filter(jobs_stmt, job_type, year)

            raw_jobs = session.exec(jobs_stmt).all()

            # Group jobs by member — deduplicate by (member_id, job_id) to
            # prevent the same job appearing twice when a member holds multiple
            # roles (e.g. "Acc Rep Selling" + "Mgmt Member") on the same job.
            mem_jobs_map: dict[str, list] = {}
            seen_job_keys: set[tuple] = set()
            for j, m_id, cl in raw_jobs:
                key = (m_id, j.ID_Jobs)
                if key in seen_job_keys:
                    continue
                seen_job_keys.add(key)
                amount = (
                    float(j.Gqm_target_sold_pricing or 0)
                    if j.Job_type == "PAR"
                    else float(j.Gqm_final_sold_pricing or 0)
                )
                job_dict = {
                    "job_id": j.ID_Jobs,
                    "type": j.Job_type,
                    "client": cl.Client_Community if cl else "—",
                    "status": (j.Job_status or "—").strip(),
                    "service": j.Service_type or "—",
                    "date": (j.Date_assigned or j.Estimated_start_date).strftime("%Y-%m-%d") if (j.Date_assigned or j.Estimated_start_date) else "—",
                    "quoted_target_sold": float(j.Gqm_target_sold_pricing or 0),
                    "amount": amount,
                    "adj_formula": float(j.Gqm_adj_formula_pricing or 0),
                    "pct": float((j.Gqm_target_return if j.Job_type in ("PTL", "PAR") else j.Gqm_final_percentage) or 0)
                }
                mem_jobs_map.setdefault(m_id, []).append(job_dict)

            for m in members_list:
                m_jobs = mem_jobs_map.get(m.ID_Member, [])
                jobs_data.append({
                    "id":           m.ID_Member,
                    "name":         m.Member_Name,
                    "company_role": m.Company_Role,
                    "job_count":    len(m_jobs),
                    "total_quoted": sum(j["quoted_target_sold"] for j in m_jobs),
                    "jobs":         m_jobs,
                })

    total_pages = (total_members + limit - 1) // limit if total_members else 1

    return jsonify({
        "type": job_type,
        "year": year,
        "pipeline_statuses": target_statuses,
        "pagination": {
            "page": page,
            "limit": limit,
            "total_members": int(total_members),
            "total_pages": int(total_pages),
        },
        "members": jobs_data
    }), 200


# =============================================================================
# ENDPOINT: Jobs Summary (paginated full job list)
# =============================================================================

@job_metrics_bp.get("/summary")
def jobs_summary():
    """
    GET /job_metrics/summary?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=50
    Paginated list of all jobs with key financial fields for the detail table.
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    year = _norm_year(request.args.get("year"))
    page = max(_safe_int(request.args.get("page"),  1), 1)
    limit = min(max(_safe_int(request.args.get("limit"), 50), 1), 200)
    offset = (page - 1) * limit

    client_id = request.args.get("client_id")

    with get_session() as session:
        # Build filter conditions
        conditions = [Job.ID_Jobs.is_not(None)]
        if job_type != "ALL":
            conditions.append(Job.Job_type == job_type)
        if year:
            conditions.append(_year_expr(job_type, year))
        if client_id:
            conditions.append(Job.ID_Client == client_id)

        where_clause = and_(*conditions)

        # Total count
        total = session.exec(
            select(func.count(Job.ID_Jobs)).where(where_clause)
        ).one() or 0

        # Fetch jobs + client
        stmt = (
            select(Job, Client)
            .outerjoin(Client, Client.ID_Client == Job.ID_Client)
            .where(where_clause)
            .order_by(Job.Date_assigned.desc().nullslast(), Job.ID_Jobs.desc())
            .offset(offset)
            .limit(limit)
        )
        raw = session.exec(stmt).all()

        # Fetch rep names for these jobs in one query
        job_ids = [j.ID_Jobs for j, _ in raw]
        rep_map: dict = {}
        if job_ids:
            rep_stmt = (
                select(JobMemberLink.job_id,
                       Member.Member_Name, JobMemberLink.rol)
                .join(Member, Member.ID_Member == JobMemberLink.member_id)
                .where(
                    JobMemberLink.job_id.in_(job_ids),
                    JobMemberLink.rol.in_(["Acc Rep Selling", "Mgmt Member"]),
                )
            )
            for jid, mname, rol in session.exec(rep_stmt).all():
                # Prefer Acc Rep Selling when both roles exist for same job
                if jid not in rep_map or rol == "Acc Rep Selling":
                    rep_map[jid] = mname

        # Build output rows
        jobs_out = []
        for j, cl in raw:
            d = j.Date_assigned or j.Estimated_start_date
            pct = float((j.Gqm_target_return if j.Job_type in (
                "PTL", "PAR") else j.Gqm_final_percentage) or 0)
            jobs_out.append({
                "job_id":      j.ID_Jobs,
                "type":        j.Job_type,
                "client":      cl.Client_Community if cl else "—",
                "rep":         rep_map.get(j.ID_Jobs, "—"),
                "status":      (j.Job_status or "—").strip(),
                "service":     j.Service_type or "—",
                "date":        d.strftime("%Y-%m-%d") if d else "—",
                "formula":     float(j.Gqm_formula_pricing or 0),
                "adj_formula": float(j.Gqm_adj_formula_pricing or 0),
                "target":      float(j.Gqm_target_sold_pricing or 0),
                "final":       float(j.Gqm_final_sold_pricing or 0),
                "pct":         pct,
                "premium":     float(j.Gqm_premium_in_money or 0),
            })

    total_pages = (total + limit - 1) // limit if total else 1

    return jsonify({
        "pagination": {
            "page":        page,
            "limit":       limit,
            "total":       int(total),
            "total_pages": int(total_pages),
        },
        "jobs": jobs_out,
    }), 200
