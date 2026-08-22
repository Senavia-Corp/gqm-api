from __future__ import annotations
from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy import func, nulls_last
from src.models.ClientModel import Client
from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.MemberModel import Member
from src.models.link_models.JobMember import JobMemberLink
from src.services.metrics.jobs_metrics_service import get_jobs_dashboard_data
from src.services.metrics.metrics_shared import (
    _apply_year_filter,
    _norm_job_type,
    _norm_year,
    _normalize_status_str,
    QUOTE_PIPELINE_BY_TYPE,
    quote_owner_id_expr,
    universo_cotizaciones,
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
# ENDPOINT: Jobs Member Pipeline (cotizaciones abiertas por miembro)
# =============================================================================

def _pipeline_statuses_payload(job_type: str):
    """Los estados que ESTA respuesta esta mostrando, para que la UI los nombre."""
    if job_type == "ALL":
        return {t: sorted(s) for t, s in QUOTE_PIPELINE_BY_TYPE.items()}
    return sorted(QUOTE_PIPELINE_BY_TYPE.get(job_type, set()))


@job_metrics_bp.get("/member-pipeline")
def jobs_member_pipeline():
    """
    GET /job_metrics/member-pipeline?type=ALL|QID|PTL|PAR&year=2025&page=1&limit=10

    Miembros con cotizaciones abiertas, UNA fila por job y UN solo dueno.

    Filtraba por `PENDING_ALL`, la union aplanada de los buckets pendientes de los
    tres tipos, y encima sin emparejar estado con tipo de job. En produccion eso
    daba 1.843 filas de las que 1.697 eran `Waiting for Approval` y 93 `HOLD`: la
    seccion se llama «P/Quote» y el estado del titulo era el 3% de lo que mostraba.
    Ademas unia `job_member` por los dos roles a la vez, asi que un job con Acc Rep
    y Mgmt Member aparecia bajo los dos miembros y la tabla no sumaba (Paola Colman
    salia con 658 filas para 553 jobs).
    """
    job_type = _norm_job_type(request.args.get("type")) or "ALL"
    year = _norm_year(request.args.get("year"))

    page = max(_safe_int(request.args.get("page"), 1), 1)
    limit = _safe_int(request.args.get("limit"), 10)
    offset = (page - 1) * limit

    tipos = ["QID", "PTL", "PAR"] if job_type == "ALL" else [job_type]
    tipos_cotizables = [t for t in tipos if QUOTE_PIPELINE_BY_TYPE.get(t)]

    def _respuesta(members, total_members, unassigned, reason=None):
        total_pages = (total_members + limit - 1) // limit if total_members else 1
        payload = {
            "type": job_type,
            "year": year,
            "pipeline_statuses": _pipeline_statuses_payload(job_type),
            "unassigned_count": int(unassigned),
            "pagination": {
                "page": page,
                "limit": limit,
                "total_members": int(total_members),
                "total_pages": int(total_pages),
            },
            "members": members,
        }
        if reason:
            payload["reason"] = reason
        return jsonify(payload), 200

    # PAR no tiene etapa de cotizacion: nace aprobado y entra en In Progress. Se
    # responde sin tocar la BD y DICIENDO por que, en vez de una lista vacia muda.
    if not tipos_cotizables:
        return _respuesta([], 0, 0, reason="no_quote_stage")

    universo = universo_cotizaciones(tipos_cotizables, year)

    with get_session() as session:
        # Cotizaciones sin nadie en el rol dueno. No se inventa una asignacion: se
        # cuentan aparte para poder decirlo en la UI. Hoy son 3 = QID41283 y QID6591
        # (sin NINGUN miembro enlazado) + el unico PTL en `Received-Stand By`, que
        # no tiene Mgmt Member. Por eso la pestana PTL sale vacia y es correcto.
        unassigned = session.exec(
            select(func.count())
            .select_from(universo)
            .where(universo.c.owner_id.is_(None))
        ).one() or 0

        conteo = (
            select(
                universo.c.owner_id.label("owner_id"),
                func.count().label("n"),
            )
            .where(universo.c.owner_id.is_not(None))
            .group_by(universo.c.owner_id)
            .subquery("conteo")
        )

        total_members = session.exec(
            select(func.count()).select_from(conteo)
        ).one() or 0

        members_list = session.exec(
            select(Member)
            .join(conteo, conteo.c.owner_id == Member.ID_Member)
            .order_by(conteo.c.n.desc(), Member.Member_Name)
            .offset(offset)
            .limit(limit)
        ).all()
        member_ids = [m.ID_Member for m in members_list]

        mem_jobs_map: dict[str, list] = {}
        if member_ids:
            # Orden determinista: antes no habia ORDER BY ninguno y las filas
            # salian en el orden que le diera a la BD.
            fecha = func.coalesce(Job.Date_assigned, Job.Estimated_start_date)
            raw_jobs = session.exec(
                select(Job, universo.c.owner_id, Client)
                .select_from(universo)
                .join(Job, Job.ID_Jobs == universo.c.job_id)
                .outerjoin(Client, Client.ID_Client == Job.ID_Client)
                .where(universo.c.owner_id.in_(member_ids))
                .order_by(nulls_last(fecha.desc()), Job.ID_Jobs.desc())
            ).all()

            for j, owner_id, cl in raw_jobs:
                # NULL no es 0: en produccion 38 de las 50 cotizaciones no tienen
                # `Gqm_target_sold_pricing` y ninguna lo tiene a 0 de verdad, asi
                # que todos los «$0.00» que se veian eran datos ausentes.
                target = j.Gqm_target_sold_pricing
                target = float(target) if target is not None else None
                d = j.Date_assigned or j.Estimated_start_date
                mem_jobs_map.setdefault(owner_id, []).append({
                    "job_id": j.ID_Jobs,
                    "type": j.Job_type,
                    "client": cl.Client_Community if cl else "—",
                    "status": _normalize_status_str(j.Job_status),
                    "service": j.Service_type or "—",
                    "date": d.strftime("%Y-%m-%d") if d else "—",
                    "quoted_target_sold": target,
                    "amount": target,
                    "adj_formula": float(j.Gqm_adj_formula_pricing or 0),
                    "pct": float((j.Gqm_target_return if j.Job_type in ("PTL", "PAR") else j.Gqm_final_percentage) or 0),
                })

        jobs_data = []
        for m in members_list:
            m_jobs = mem_jobs_map.get(m.ID_Member, [])
            montos = [j["quoted_target_sold"] for j in m_jobs if j["quoted_target_sold"] is not None]
            jobs_data.append({
                "id":           m.ID_Member,
                "name":         m.Member_Name,
                "company_role": m.Company_Role,
                "job_count":    len(m_jobs),
                "total_quoted": sum(montos) if montos else None,
                "jobs":         m_jobs,
            })

    return _respuesta(jobs_data, total_members, unassigned)


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
    subcontractor_id = request.args.get("subcontractor_id")
    technician_id = request.args.get("technician_id")
    status = request.args.get("status")

    with get_session() as session:
        # Build filter conditions
        conditions = [Job.ID_Jobs.is_not(None)]
        if job_type != "ALL":
            conditions.append(Job.Job_type == job_type)
        if year:
            conditions.append(_year_expr(job_type, year))
        if client_id:
            conditions.append(Job.ID_Client == client_id)
        if status:
            if status.upper() == "PAID":
                conditions.append(func.lower(Job.Job_status).in_(["paid"]))
            else:
                conditions.append(func.lower(Job.Job_status) == status.lower())
        if subcontractor_id:
            from src.models.link_models.JobSubcontractor import JobSubcontractorLink
            conditions.append(
                Job.ID_Jobs.in_(
                    select(JobSubcontractorLink.job_id).where(
                        JobSubcontractorLink.subcontr_id == subcontractor_id)
                )
            )
        if technician_id:
            from src.models.link_models.JobTechnician import JobTechnicianLink
            conditions.append(
                Job.ID_Jobs.in_(
                    select(JobTechnicianLink.job_id).where(
                        JobTechnicianLink.technician_id == technician_id)
                )
            )

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
                "status":      _normalize_status_str(j.Job_status),
                "service":     j.Service_type or "—",
                "date":        d.strftime("%Y-%m-%d") if d else "—",
                "location":    j.Project_location or None,
                "formula":     float(j.Gqm_formula_pricing or 0),
                "adj_formula": float(j.Gqm_adj_formula_pricing or 0),
                "target":      float(j.Gqm_target_sold_pricing or 0),
                # Revenue PAR = lo facturado (final_sold, fallback a target si 0).
                # La fórmula es el costo del técnico, no el revenue. Misma regla
                # que _par_revenue_expr del KPI.
                "final":       float(((j.Gqm_final_sold_pricing or j.Gqm_target_sold_pricing)
                                      if j.Job_type == "PAR"
                                      else j.Gqm_final_sold_pricing) or 0),
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
