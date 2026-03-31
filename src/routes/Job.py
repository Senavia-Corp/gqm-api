# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job, JobCreate, JobUpdate
from ..models.MemberModel import Member
from ..models.ClientModel import Client
from ..models.SubcontractorModel import Subcontractor
from ..models.FinancialDocModel import FinancialDocument
from ..models.link_models.JobMember import JobMemberLink
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload, selectinload, load_only
from sqlalchemy import func, extract, or_, and_
from ..podio.services.job_services import podio_jobs_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid
from ..utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from ..utils.mappers.to_podio.par_mapper import map_job_to_podio_par
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.audit import audit
from ..utils.job_calculator import recalculate_and_apply
from datetime import date
from src.services.commission_service import process_job_to_commissions
from src.utils.middleware.auth.routes_protection import require_permission
from src.utils.policy_evaluator import PolicyEvaluator
from src.models.JobModel import JobReadBasic
from flask import g

def serialize_job(job_dict, policies):
    if not isinstance(job_dict, dict):
        if hasattr(job_dict, "model_dump"):
            job_dict = job_dict.model_dump()
        else:
            return job_dict
    if PolicyEvaluator.evaluate(policies, "job:read"):
        return job_dict
    elif PolicyEvaluator.evaluate(policies, "job:read_basics"):
        return JobReadBasic.model_validate(job_dict).model_dump(exclude_unset=True)
    return job_dict


# Blueprint de Jobs:
job_bp = Blueprint("job_blueprint", __name__, url_prefix="/jobs")

MONTH_NUMBER = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4,
    "MAY": 5, "JUNE": 6, "JULY": 7, "AUGUST": 8,
    "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#

@job_bp.get("/")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def list_jobs():

    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client),
                joinedload(Job.members),
                joinedload(Job.multipliers),
                joinedload(Job.attachments),
                joinedload(Job.tasks),
                joinedload(Job.estimate_costs),
                joinedload(Job.payment_units),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.technicians),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.orders),
                joinedload(Job.tlactivity),
                joinedload(Job.change_orders),
                joinedload(Job.building_dept),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        job_ids = [job.ID_Jobs for job in results]
        roles_statement = (
            select(JobMemberLink)
            .where(JobMemberLink.job_id.in_(job_ids))
        )
        roles = session.exec(roles_statement).all()
        roles_map = {
            (link.job_id, link.member_id): link.rol
            for link in roles
        }

        jobs_data = []
        for job in results:
            job_dict = add_relationships(
                job, ["client", "members", "multipliers", "building_dept", "change_orders",
                      "attachments", "subcontractors.technicians", "tasks", "tlactivity",
                      "subcontractors.orders", "estimate_costs", "payment_units"])
            for member in job_dict.get("members", []):
                key = (job.ID_Jobs, member["ID_Member"])
                member["rol"] = roles_map.get(key)
            jobs_data.append(job_dict)

        policies = getattr(g, "user_policies", [])
        return [serialize_job(j, policies) for j in jobs_data], 200


@job_bp.get("/jobs_table")
@require_permission(["job:read", "job:read_basics"])
def list_jobs_table():
    try:
        page = int(request.args.get("page",  1))
        limit = int(request.args.get("limit", 10))
        if page < 1:
            page = 1
        if limit < 1:
            limit = 10
        limit = min(limit, 200)

        job_type = request.args.get("type")
        status = request.args.get("status")
        year = request.args.get("year")
        search = request.args.get("search", "").strip()

        if job_type:
            job_type = job_type.upper()

        year_int = None
        if year:
            try:
                year_int = int(year)
            except ValueError:
                return jsonify({"detail": "Invalid year"}), 400

        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    load_only(
                        Job.ID_Jobs, Job.Job_type, Job.Project_name,
                        Job.Project_location, Job.Job_status, Job.Date_assigned,
                        Job.Gqm_formula_pricing, Job.ID_Client, Job.Estimated_start_date, Job.Gqm_target_sold_pricing,
                        Job.Gqm_target_return
                    ),
                    selectinload(Job.client).load_only(
                        Client.ID_Client, Client.Client_Community),
                    selectinload(Job.members).load_only(
                        Member.ID_Member, Member.Member_Name),
                )
            )

            if job_type:
                statement = statement.where(Job.Job_type == job_type)
            if status:
                statement = statement.where(Job.Job_status == status)

            if search:
                pattern = f"%{search}%"
                statement = statement.where(
                    or_(
                        Job.Project_name.ilike(pattern),
                        Job.ID_Jobs.ilike(pattern),
                    )
                )

            if year_int is not None:
                if job_type == "PTL":
                    statement = statement.where(
                        Job.Estimated_start_date.is_not(None),
                        extract("year", Job.Estimated_start_date) == year_int)
                elif job_type:
                    statement = statement.where(
                        Job.Date_assigned.is_not(None),
                        extract("year", Job.Date_assigned) == year_int)
                else:
                    statement = statement.where(or_(
                        and_(Job.Job_type == "PTL",
                             Job.Estimated_start_date.is_not(None),
                             extract("year", Job.Estimated_start_date) == year_int),
                        and_(Job.Job_type != "PTL",
                             Job.Date_assigned.is_not(None),
                             extract("year", Job.Date_assigned) == year_int)))

            count_stmt = select(func.count()).select_from(Job)
            if job_type:
                count_stmt = count_stmt.where(Job.Job_type == job_type)
            if status:
                count_stmt = count_stmt.where(Job.Job_status == status)

            if search:
                pattern = f"%{search}%"
                count_stmt = count_stmt.where(
                    or_(
                        Job.Project_name.ilike(pattern),
                        Job.ID_Jobs.ilike(pattern),
                    )
                )

            if year_int is not None:
                if job_type == "PTL":
                    count_stmt = count_stmt.where(
                        Job.Estimated_start_date.is_not(None),
                        extract("year", Job.Estimated_start_date) == year_int)
                elif job_type:
                    count_stmt = count_stmt.where(
                        Job.Date_assigned.is_not(None),
                        extract("year", Job.Date_assigned) == year_int)
                else:
                    count_stmt = count_stmt.where(or_(
                        and_(Job.Job_type == "PTL",
                             Job.Estimated_start_date.is_not(None),
                             extract("year", Job.Estimated_start_date) == year_int),
                        and_(Job.Job_type != "PTL",
                             Job.Date_assigned.is_not(None),
                             extract("year", Job.Date_assigned) == year_int)))

            total = session.exec(count_stmt).one()
            offset = (page - 1) * limit
            statement = statement.order_by(
                Job.ID_Jobs.desc()).offset(offset).limit(limit)
            results = session.exec(statement).unique().all()

            if not results:
                return jsonify({"page": page, "limit": limit, "total": total, "results": []}), 200

            job_ids = [j.ID_Jobs for j in results if j.ID_Jobs]
            roles = session.exec(
                select(JobMemberLink).where(JobMemberLink.job_id.in_(job_ids))).all()
            roles_map = {(l.job_id, l.member_id): l.rol for l in roles}

            out = []
            for j in results:
                j_dict = {
                    "ID_Jobs": j.ID_Jobs, "Job_type": j.Job_type,
                    "Project_name": j.Project_name, "Project_location": j.Project_location,
                    "Job_status": j.Job_status, "Date_assigned": j.Date_assigned,
                    "Estimated_start_date": j.Estimated_start_date,
                    "Gqm_formula_pricing": j.Gqm_formula_pricing,
                    "Gqm_target_return": j.Gqm_target_return,
                    "Gqm_target_sold_pricing": j.Gqm_target_sold_pricing,
                    "client": None, "members": [],
                }
                if j.client:
                    j_dict["client"] = {
                        "ID_Client": j.client.ID_Client,
                        "Client_Community": getattr(j.client, "Client_Community", None)}
                for m in (j.members or []):
                    j_dict["members"].append({
                        "ID_Member": m.ID_Member,
                        "Member_Name": getattr(m, "Member_Name", None),
                        "rol": roles_map.get((j.ID_Jobs, m.ID_Member))})
                out.append(j_dict)

            policies = getattr(g, "user_policies", [])
            out = [serialize_job(j, policies) for j in out]
            return jsonify({"page": page, "limit": limit, "total": total, "results": out}), 200

    except Exception as e:
        print(f"Error jobs_table: {e}")
        return jsonify({"detail": "Error interno del servidor.", "code": "internal_error"}), 500


@job_bp.get("/<id_job>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
def get_job_by_id(id_job):
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.tasks), joinedload(Job.estimate_costs),
                joinedload(Job.payment_units),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.technicians),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.orders),
                joinedload(Job.building_dept),
                selectinload(Job.financial_docs).options(
                    selectinload(FinancialDocument.financial_doc_items),
                    selectinload(FinancialDocument.financial_transactions)))
            .where(Job.ID_Jobs == id_job)
        )
        obj = session.exec(statement).unique().first()
        if not obj:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        roles_statement = select(JobMemberLink).where(
            JobMemberLink.job_id == obj.ID_Jobs)
        roles = session.exec(roles_statement).all()
        roles_map = {}
        for link in roles:
            if link.member_id not in roles_map:
                roles_map[link.member_id] = []
            roles_map[link.member_id].append(link.rol)

        job_data = add_relationships(
            obj, ["client", "members", "multipliers", "building_dept", "change_orders",
                  "attachments", "subcontractors.technicians", "tasks",
                  "subcontractors.orders", "estimate_costs", "payment_units",
                  "financial_docs.financial_doc_items", "financial_docs.financial_transactions"])

        for member in job_data.get("members", []):
            member["rol"] = roles_map.get(member["ID_Member"], [])

        job_data.pop("ID_Client", None)
        policies = getattr(g, "user_policies", [])
        return serialize_job(job_data, policies), 200


@job_bp.get("/by-type-year")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def get_jobs_by_type_year():
    job_type = request.args.get("type")
    year = request.args.get("year")
    if not job_type or not year:
        raise AppException(
            "Debes enviar los parámetros 'type' y 'year'.", "missing_query_params", 400)
    year_digit = year[-1]
    pattern = f"{job_type.upper()}{year_digit}%"
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.tasks), joinedload(Job.estimate_costs),
                joinedload(Job.payment_units),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.technicians),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.orders),
                joinedload(Job.tlactivity), joinedload(Job.change_orders),
                joinedload(Job.building_dept))
            .where(Job.ID_Jobs.like(pattern))
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        job_ids = [job.ID_Jobs for job in results]
        roles = session.exec(
            select(JobMemberLink).where(JobMemberLink.job_id.in_(job_ids))).all()
        roles_map = {(l.job_id, l.member_id): l.rol for l in roles}
        jobs_data = []
        for job in results:
            job_dict = add_relationships(
                job, ["client", "members", "multipliers", "building_dept", "change_orders",
                      "attachments", "subcontractors.technicians", "tasks", "tlactivity",
                      "subcontractors.orders", "estimate_costs", "payment_units"])
            for member in job_dict.get("members", []):
                key = (job.ID_Jobs, member["ID_Member"])
                member["rol"] = roles_map.get(key)
            jobs_data.append(job_dict)
        return jobs_data, 200


@job_bp.get("/status/<status>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def list_jobs_by_status(status):
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.subcontractors).joinedload(Subcontractor.technicians))
            .where(Job.Job_status == status)
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        jobs_data = [add_relationships(job, ["client", "members", "multipliers",
                     "attachments", "subcontractors.technicians"]) for job in results]
        return jobs_data, 200


@job_bp.get("/client/<id_client>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def get_job_by_clientID(id_client):
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.subcontractors).joinedload(Subcontractor.technicians))
            .where(Job.ID_Client == id_client)
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]) for job in results], 200


@job_bp.get("/member/<id_member>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def get_job_by_memberID(id_member):
    with get_session() as session:
        statement = (
            select(Job).join(Job.members)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.subcontractors).joinedload(Subcontractor.technicians))
            .where(Member.ID_Member == id_member)
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]) for job in results], 200


@job_bp.get("/by-member-role")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
def get_jobs_by_member_and_role():
 
    member_id = request.args.get("member_id")
    rol       = request.args.get("rol")
 
    if not member_id:
        raise AppException("member_id es requerido", "missing_params", 400)
    if not rol:
        raise AppException("rol es requerido", "missing_params", 400)
 
    job_type = request.args.get("type", "").strip().upper() or None
    year_raw = request.args.get("year", "").strip()
    month_raw= request.args.get("month", "").strip().upper()
    page     = max(1, int(request.args.get("page",  1)))
    limit    = min(200, max(1, int(request.args.get("limit", 50))))
 
    # Validar y convertir año
    year_int  = None
    if year_raw:
        try:
            year_int = int(year_raw)
        except ValueError:
            raise AppException("El parámetro 'year' debe ser un número entero.", "invalid_year", 400)
 
    # Validar y convertir mes
    month_int = None
    if month_raw:
        month_int = MONTH_NUMBER.get(month_raw)
        if month_int is None:
            raise AppException(
                f"Mes inválido: '{month_raw}'. Usa el nombre en inglés (e.g. JANUARY).",
                "invalid_month", 400
            )
 
    with get_session() as session:
 
        # ── Base: join con la tabla link filtrando por miembro y rol ─────────
        statement = (
            select(Job)
            .join(JobMemberLink, Job.ID_Jobs == JobMemberLink.job_id)
            .where(
                JobMemberLink.member_id == member_id,
                JobMemberLink.rol       == rol,
            )
        )
 
        # ── Filtro por tipo de trabajo ────────────────────────────────────────
        if job_type:
            statement = statement.where(Job.Job_type == job_type)
 
        # ── Filtros por año / mes ─────────────────────────────────────────────
        # Para PTL usamos Estimated_start_date; para el resto, Date_assigned.
        # Si no se sabe el tipo, aplicamos la lógica combinada con OR.
 
        def _date_col(jtype):
            """Devuelve la columna de fecha correcta según el tipo."""
            return Job.Estimated_start_date if jtype == "PTL" else Job.Date_assigned
 
        if year_int is not None or month_int is not None:
            if job_type:
                # Tipo conocido → filtro simple sobre la columna correspondiente
                date_col = _date_col(job_type)
                statement = statement.where(date_col.is_not(None))
                if year_int  is not None:
                    statement = statement.where(extract("year",  date_col) == year_int)
                if month_int is not None:
                    statement = statement.where(extract("month", date_col) == month_int)
            else:
                # Tipo desconocido → OR entre PTL y no-PTL
                from sqlalchemy import and_, or_ as sa_or
                conditions = []
                for jt, col in [("PTL", Job.Estimated_start_date),
                                 ("QID", Job.Date_assigned),
                                 ("PAR", Job.Date_assigned)]:
                    cond = [Job.Job_type == jt, col.is_not(None)]
                    if year_int  is not None:
                        cond.append(extract("year",  col) == year_int)
                    if month_int is not None:
                        cond.append(extract("month", col) == month_int)
                    conditions.append(and_(*cond))
                statement = statement.where(sa_or(*conditions))
 
        # ── Paginación ────────────────────────────────────────────────────────
        count_stmt = (
            select(func.count())
            .select_from(
                select(Job.ID_Jobs)
                .join(JobMemberLink, Job.ID_Jobs == JobMemberLink.job_id)
                .where(
                    JobMemberLink.member_id == member_id,
                    JobMemberLink.rol       == rol,
                )
                .subquery()
            )
        )
        # (El total sin filtros de fecha/tipo es suficiente para la UI,
        #  pero si quieres el total exacto con todos los filtros, construye
        #  count_stmt con las mismas condiciones que statement arriba.)
 
        offset = (page - 1) * limit
        statement = statement.offset(offset).limit(limit)
 
        results = session.exec(statement).all()
 
        if not results:
            return jsonify({
                "page": page, "limit": limit,
                "total": 0,  "results": []
            }), 200
 
        jobs_data = [
            {
                "ID_Jobs":              j.ID_Jobs,
                "Job_type":             j.Job_type,
                "Project_name":         j.Project_name,
                "Project_location":     j.Project_location,
                "Job_status":           j.Job_status,
                "Date_assigned":        j.Date_assigned.isoformat()  if j.Date_assigned        else None,
                "Estimated_start_date": j.Estimated_start_date.isoformat() if j.Estimated_start_date else None,
                "Gqm_premium_in_money": j.Gqm_premium_in_money,
                "Gqm_target_return":    j.Gqm_target_return,
                "ID_Client":            j.ID_Client,
            }
            for j in results
        ]
 
        return jsonify({
            "page":    page,
            "limit":   limit,
            "total":   len(jobs_data),   # reemplaza con count real si lo necesitas
            "results": jobs_data,
        }), 200


@job_bp.get("/subcontractor/<id_subcontractor>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def get_job_by_subcontrID(id_subcontractor):
    with get_session() as session:
        statement = (
            select(Job).join(Job.subcontractors)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.subcontractors).joinedload(Subcontractor.technicians))
            .where(Subcontractor.ID_Subcontractor == id_subcontractor)
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]) for job in results], 200


@job_bp.get("/type/<type>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def list_jobs_by_type(type):
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.subcontractors).joinedload(Subcontractor.technicians))
            .where(Job.Job_type == type)
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]) for job in results], 200


@job_bp.get("/date_assigned/<date>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def list_jobs_by_date(date):
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.subcontractors).joinedload(Subcontractor.technicians))
            .where(Job.Date_assigned == date)
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]) for job in results], 200


# ---------------------------------------------------------------------------
# WRITE ROUTES
# ---------------------------------------------------------------------------

@job_bp.post("/")
@require_permission("job:create")
@handle_exceptions()
@audit("Job created", job_id_from="response")
def create_job():

    data = request.get_json()
    job_data = JobCreate.model_validate(data)
    obj = Job(**job_data.model_dump(exclude_unset=False, exclude_none=False))

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year", 400)

    with get_session() as session:

        if sync_podio:
            if obj.Job_type == "QID":
                podio_fields = map_job_to_podio_qid(obj, session=session)
            elif obj.Job_type == "PTL":
                podio_fields = map_job_to_podio_ptl(obj, session=session)
            elif obj.Job_type == "PAR":
                podio_fields = map_job_to_podio_par(obj, session=session)
            else:
                raise AppException(
                    f"Job_type inválido: {obj.Job_type}", "invalid_job_type", 400)

            podio_service = podio_jobs_router.get_service(
                job_type=obj.Job_type, year=year)
            podio_response = podio_service.create_item(podio_fields)

            if not podio_response or not podio_response.get("item_id"):
                raise AppException(
                    "No se pudo crear el item en Podio.", "podio_creation_failed", 502)

            obj.podio_item_id = podio_response["item_id"]
            item = podio_service.get_item(obj.podio_item_id)
            formatted_id = item.get("app_item_id_formatted")

            if not formatted_id:
                raise AppException(
                    "No se pudo obtener el ID formateado desde Podio.",
                    "podio_formatted_id_missing", 502)

            obj.ID_Jobs = formatted_id
            register_event(obj.podio_item_id)

        else:
            prefix_map = {
                "QID": "QID-I",
                "PTL": "PTL-I",
                "PAR": "PAR-I"
            }

            if obj.Job_type not in prefix_map:
                raise AppException("Job no encontrado.", "job_not_found", 404)
            obj.ID_Jobs = generate_custom_id(
                session, Job, "ID_Jobs", prefix_map[obj.Job_type])
            obj.podio_item_id = None

        save_with_retry(session, obj)
        logger.info("✅ Job creado | job_id=%s | podio_item_id=%s",
                    obj.ID_Jobs, obj.podio_item_id)
        return obj.model_dump(), 201


@job_bp.patch("/<id_job>")
@require_permission("job:update")
@handle_exceptions()
@audit("Job updated", id_param="id_job")
def update_job(id_job):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    dry_run = request.args.get("dry_run", "false").lower() == "true"
    year = request.args.get("year", type=int)
    data = request.get_json()

    with get_session() as session:
        obj = session.exec(select(Job).where(Job.ID_Jobs == id_job)).first()
        if not obj:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        # Guardar el estado anterior para saber si REALMENTE cambió a PAID ahora
        previous_status = obj.Job_status

        update_data = JobUpdate.model_validate(
            data).model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(obj, key, value)

        if not dry_run:
            save_with_retry(session, obj)
            logger.info("🔄 Job actualizado | job_id=%s", id_job)

            # --- 🎯 TRIGGER DE COMISIONES (LOCAL) ---
            # Normalizamos ambos para la comparación (Case-Insensitive)
            current_status_upper = (obj.Job_status or "").upper()
            previous_status_upper = (previous_status or "").upper()

            if current_status_upper == "PAID" and previous_status_upper != "PAID":
                logger.info(
                    "💰 Detectado cambio a PAID. Procesando comisiones locales...")
                process_job_to_commissions(obj, session)
            # ---------------------------------------------------------------------------------

        # ── Recálculo automático de campos derivados ──────────────────────
        recalculate_and_apply(id_job, session)
        session.commit()
        session.refresh(obj)
        # ─────────────────────────────────────────────────────────────────

        if (sync_podio or dry_run) and obj.podio_item_id:
            if obj.Job_type == "QID":
                podio_fields = map_job_to_podio_qid(obj, session=session)
            elif obj.Job_type == "PTL":
                podio_fields = map_job_to_podio_ptl(obj, session=session)
            elif obj.Job_type == "PAR":
                podio_fields = map_job_to_podio_par(obj, session=session)
            else:
                raise AppException(
                    f"Job_type inválido: {obj.Job_type}", "invalid_job_type", 400)

            if dry_run:
                return {"dry_run": True, "podio_payload": podio_fields}, 200

            podio_service = podio_jobs_router.get_service(
                job_type=obj.Job_type, year=year)
            try:
                podio_service.update_item(int(obj.podio_item_id), podio_fields)
                register_event(obj.podio_item_id)
                logger.info("🔄 Job actualizado en Podio | job_id=%s | podio_item_id=%s",
                            id_job, obj.podio_item_id)
            except Exception:
                logger.exception("❌ Error actualizando Job en Podio | job_id=%s | podio_item_id=%s",
                                 id_job, obj.podio_item_id)
                raise AppException(
                    "Error al actualizar el Job en Podio.", "podio_update_failed", 502)

        return obj.model_dump(), 200


@job_bp.delete("/<id_job>")
@require_permission("job:delete")
@handle_exceptions()
@audit("Job deleted", id_param="id_job")
def delete_job(id_job):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    with get_session() as session:
        obj = session.exec(select(Job).where(Job.ID_Jobs == id_job)).first()
        if not obj:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        if sync_podio and obj.podio_item_id:
            podio_service = podio_jobs_router.get_service(
                job_type=obj.Job_type, year=year)
            try:
                podio_service.delete_item(int(obj.podio_item_id))
                register_event(obj.podio_item_id)
                logger.info("🗑️ Job eliminado en Podio | job_id=%s | podio_item_id=%s",
                            id_job, obj.podio_item_id)
            except Exception:
                logger.exception("❌ Error eliminando Job en Podio | job_id=%s | podio_item_id=%s",
                                 id_job, obj.podio_item_id)
                raise AppException(
                    "Error al eliminar el Job en Podio.", "podio_delete_failed", 502)

        delete_with_retry(session, obj)
        logger.info("🗑️ Job eliminado | job_id=%s", id_job)
        return jsonify({"message": f"Job {id_job} eliminado correctamente"}), 200
