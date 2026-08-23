# ============ Lógica de rutas =================

from flask import Blueprint, g, jsonify, request
from sqlmodel import select, delete
from ..database.db_sqlmodel import get_session
from flask import send_file, request
from datetime import datetime, date
import io
from ..models.JobModel import Job, JobCreate, JobUpdate
from ..models.MemberModel import Member
from ..models.ClientModel import Client
from ..models.ParentMgmtCoModel import ParentMgmtCo
from ..models.SubcontractorModel import Subcontractor
from ..models.FinancialDocModel import FinancialDocument
from ..models.OrderModel import Order
from ..models.link_models.JobMember import JobMemberLink
from ..models.link_models.JobMultiplierR import JobMultiplierRLink
from ..models.link_models.JobSubcontractor import JobSubcontractorLink
from ..models.link_models.JobTechnician import JobTechnicianLink
from ..models.link_models.JobPaymentU import JobPaymentULink
from ..models.link_models.ClientLinks import ClientManagerLink
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload, selectinload, load_only
from sqlalchemy import func, extract, or_, and_, case
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
from src.services.commission_service import process_job_to_commissions
from src.utils.middleware.auth.routes_protection import (
    portal_scope,
    require_permission,
    scope_jobs_statement,
)
from src.utils.policy_evaluator import PolicyEvaluator
from src.utils.job_app_year import expr_anio_app, resolver_anio_app
from src.models.JobModel import JobReadBasic
from src.models.ComDetailModel import CommissionDetail
from src.models.ComGroupModel import CommissionGroup
from src.models.CommissionModel import Commission
from flask import g
# Para exportar el excel
from src.services.excel_report.export_schema import JobExportRequest
from src.services.excel_report.export_service import generate_jobs_excel


def serialize_job(job_dict, policies):
    if not isinstance(job_dict, dict):
        if hasattr(job_dict, "model_dump"):
            job_dict = job_dict.model_dump()
        else:
            return job_dict
    if PolicyEvaluator.evaluate(policies, "job:read"):
        return job_dict
    elif PolicyEvaluator.evaluate(policies, "job:read_basics"):
        return JobReadBasic.model_validate(job_dict).model_dump(mode='json', exclude_unset=True)
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
def _aplicar_filtros(stmt, *, job_type=None, status=None, year_int=None, search=None,
                     client_id=None, member_id=None, parent_mgmt_co_id=None,
                     subcontractor_id=None, date_from=None, date_to=None):
    """Los MISMOS WHERE para la consulta de filas y para la de conteo.

    Antes estaban escritos dos veces, y no eran iguales: las filas resolvían
    `?status=A,B` con `in_()` y el conteo con `ilike('A,B')`, que no casa con
    nada. El resultado era una respuesta con filas y `total: 0` — justo el
    número que el cliente mira en el panel para dar la paridad por buena.

    Sirve tanto a `select(Job)` como a `select(func.count()).select_from(Job)`.

    El año sale de `expr_anio_app()`, no de las fechas: es a qué app de Podio
    pertenece el item, que es lo que el cliente compara contra su contador. Las
    métricas y el dashboard siguen con semántica de fecha a propósito — ahí «el
    año» significa cuándo se trabajó, no en qué app vive.
    """
    if job_type:
        stmt = stmt.where(Job.Job_type == job_type)

    if status:
        # lower() + in_() en las dos ramas: `in_()` era sensible a mayúsculas
        # mientras `ilike` no, así que con y sin coma tampoco coincidían.
        valores = [s.strip().lower() for s in str(status).split(",") if s.strip()]
        if valores:
            stmt = stmt.where(func.lower(Job.Job_status).in_(valores))

    if year_int is not None:
        stmt = stmt.where(expr_anio_app() == year_int)

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Job.Project_name.ilike(pattern),
                Job.ID_Jobs.ilike(pattern),
                Job.Project_location.ilike(pattern),
                Job.Job_status.ilike(pattern),
                Job.Service_type.ilike(pattern),
                Job.client.has(Client.Client_Community.ilike(pattern)),
                Job.client.has(Client.parent_mgmt_co.has(or_(
                    ParentMgmtCo.Property_mgmt_co.ilike(pattern),
                    ParentMgmtCo.Company_abbrev.ilike(pattern)))),
                Job.members.any(Member.Member_Name.ilike(pattern))
            )
        )

    if member_id:
        stmt = stmt.where(Job.members.any(Member.ID_Member == member_id))

    if client_id:
        stmt = stmt.where(Job.ID_Client == client_id)

    if parent_mgmt_co_id:
        stmt = stmt.where(
            Job.client.has(Client.ID_Community_Tracking == parent_mgmt_co_id))

    if subcontractor_id:
        stmt = stmt.where(
            Job.subcontractors.any(
                Subcontractor.ID_Subcontractor == subcontractor_id))

    # El rango de fechas sí depende del tipo: para PTL la fecha que importa es
    # la de inicio estimado, y para el resto la de asignación.
    if date_from or date_to:
        if job_type == "PTL":
            date_col = Job.Estimated_start_date
        elif job_type:
            date_col = Job.Date_assigned
        else:
            date_col = None
            if date_from:
                stmt = stmt.where(or_(
                    and_(Job.Job_type == "PTL",
                         Job.Estimated_start_date >= date_from),
                    and_(Job.Job_type != "PTL",
                         Job.Date_assigned >= date_from)))
            if date_to:
                stmt = stmt.where(or_(
                    and_(Job.Job_type == "PTL",
                         Job.Estimated_start_date <= date_to),
                    and_(Job.Job_type != "PTL",
                         Job.Date_assigned <= date_to)))

        if date_col is not None:
            if date_from:
                stmt = stmt.where(date_col >= date_from)
            if date_to:
                stmt = stmt.where(date_col <= date_to)

    return stmt


def _filtros_de_la_peticion() -> tuple[dict, object]:
    """Lee y valida los filtros de la query string. Devuelve (filtros, error)."""
    job_type = request.args.get("type")
    if job_type:
        job_type = job_type.upper()

    date_from = date_to = None
    try:
        if request.args.get("date_from"):
            date_from = datetime.fromisoformat(request.args["date_from"])
        if request.args.get("date_to"):
            date_to = datetime.fromisoformat(request.args["date_to"])
    except ValueError:
        return {}, (jsonify(
            {"detail": "Invalid date format. Use ISO 8601 (YYYY-MM-DD)."}), 400)

    year_int = None
    if request.args.get("year"):
        try:
            year_int = int(request.args["year"])
        except ValueError:
            return {}, (jsonify({"detail": "Invalid year"}), 400)

    return {
        "job_type": job_type,
        "status": request.args.get("status"),
        "year_int": year_int,
        "search": (request.args.get("search") or "").strip(),
        "client_id": request.args.get("client_id"),
        "member_id": request.args.get("member_id"),
        "parent_mgmt_co_id": request.args.get("parent_mgmt_co_id"),
        "subcontractor_id": (request.args.get("subcontractorId")
                             or request.args.get("subcontractor_id")),
        "date_from": date_from,
        "date_to": date_to,
    }, None


@job_bp.get("/")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
def list_jobs():
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 10))
    except:
        page = 1
        limit = 10
    limit = min(limit, 200)

    # Antes esta ruta filtraba SOLO por `type` e ignoraba `year` y `status` en
    # silencio, que es peor que un 400: `/jobs/?type=QID&year=2025` devolvía
    # todos los QID de todos los años y quien verificara la paridad con curl
    # concluía una divergencia catastrófica que no existe.
    filtros, error = _filtros_de_la_peticion()
    if error:
        return error

    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client),
                selectinload(Job.members),
                selectinload(Job.multipliers),
                selectinload(Job.attachments),
                selectinload(Job.tasks),
                selectinload(Job.estimate_costs),
                selectinload(Job.payment_units),
                selectinload(Job.subcontractors).selectinload(
                    Subcontractor.technicians),
                selectinload(Job.subcontractors).selectinload(
                    Subcontractor.orders),
                selectinload(Job.tlactivity),
                selectinload(Job.change_orders),
                joinedload(Job.building_dept),
            )
        )

        statement = _aplicar_filtros(statement, **filtros)
        # Portal (sub/tech): solo sus jobs (REG-037)
        statement = scope_jobs_statement(statement)

        count_stmt = _aplicar_filtros(
            select(func.count()).select_from(Job), **filtros)
        count_stmt = scope_jobs_statement(count_stmt)
        total = session.exec(count_stmt).one()

        offset = (page - 1) * limit
        statement = statement.order_by(Job.created_at.desc(), Job.ID_Jobs.desc()).offset(offset).limit(limit)
        results = session.exec(statement).unique().all()

        if not results:
            return jsonify({"page": page, "limit": limit, "total": total, "results": []}), 200

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
        out = [serialize_job(j, policies) for j in jobs_data]
        return jsonify({
            "page": page,
            "limit": limit,
            "total": total,
            "results": out
        }), 200


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

        filtros, error = _filtros_de_la_peticion()
        if error:
            return error

        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    load_only(
                        Job.ID_Jobs, Job.Job_type, Job.Project_name,
                        Job.Project_location, Job.Job_status, Job.Date_assigned,
                        Job.Gqm_formula_pricing, Job.ID_Client, Job.Estimated_start_date, Job.Gqm_target_sold_pricing,
                        Job.Gqm_target_return, Job.Service_type, Job.created_at,
                        # Sin esto el panel no puede leer el año de la app y
                        # tiene que adivinarlo desde las fechas, que es lo que
                        # hacía y fallaba en 88 jobs.
                        Job.podio_app_year, Job.podio_item_id,
                    ),
                    selectinload(Job.client).load_only(
                        Client.ID_Client, Client.Client_Community),
                    selectinload(Job.members).load_only(
                        Member.ID_Member, Member.Member_Name),
                )
            )

            statement = _aplicar_filtros(statement, **filtros)
            # Portal (sub/tech): solo sus jobs (REG-037)
            statement = scope_jobs_statement(statement)

            # El conteo usa el MISMO constructor, no una copia a mano. La copia
            # llevaba meses divergiendo: `?status=A,B` daba filas y `total: 0`.
            count_stmt = _aplicar_filtros(
                select(func.count()).select_from(Job), **filtros)
            count_stmt = scope_jobs_statement(count_stmt)

            total = session.exec(count_stmt).one()
            offset = (page - 1) * limit
            statement = statement.order_by(
                Job.created_at.desc(), Job.ID_Jobs.desc()).offset(offset).limit(limit)
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
                    "ID_Jobs": j.ID_Jobs,
                    "Job_type": j.Job_type,
                    "Project_name": j.Project_name,
                    "Project_location": j.Project_location,
                    "Job_status": j.Job_status,
                    "Date_assigned": j.Date_assigned.isoformat() if j.Date_assigned else None,
                    "Estimated_start_date": j.Estimated_start_date.isoformat() if j.Estimated_start_date else None,
                    "Service_type": j.Service_type,
                    "Gqm_formula_pricing": j.Gqm_formula_pricing,
                    "Gqm_target_return": j.Gqm_target_return,
                    "Gqm_target_sold_pricing": j.Gqm_target_sold_pricing,
                    "created_at": j.created_at.isoformat() if hasattr(j, "created_at") and j.created_at else None,
                    # La MISMA regla que usan los filtros (`expr_anio_app`), no
                    # la columna pelada: si no coincidian, el panel filtraba por
                    # un año y mostraba otro.
                    "podio_app_year": resolver_anio_app(j),
                    "podio_item_id": j.podio_item_id,
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
            result_payload = {
                "page": page,
                "limit": limit,
                "total": total,
                "results": out
            }
            return jsonify(result_payload), 200

    except Exception as e:
        print(f"Error jobs_table: {e}")
        return jsonify({"detail": "Error interno del servidor.", "code": "internal_error"}), 500


@job_bp.get("/oldest")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
def get_oldest_job():
    """Returns the single oldest job for a parent company, ordered by effective date ASC."""
    parent_mgmt_co_id = request.args.get("parent_mgmt_co_id", "").strip()
    if not parent_mgmt_co_id:
        return jsonify({"detail": "parent_mgmt_co_id is required"}), 400

    # Effective date: Estimated_start_date for PTL, Date_assigned for all others
    effective_date = case(
        (Job.Job_type == "PTL", Job.Estimated_start_date),
        else_=Job.Date_assigned,
    )

    with get_session() as session:
        statement = (
            select(Job)
            .options(
                load_only(
                    Job.ID_Jobs, Job.Job_type, Job.Project_name,
                    Job.Project_location, Job.Job_status,
                    Job.Date_assigned, Job.Estimated_start_date,
                    Job.Service_type,
                ),
                joinedload(Job.client).load_only(
                    Client.ID_Client, Client.Client_Community,
                ),
            )
            .join(Job.client)
            .where(Client.ID_Community_Tracking == parent_mgmt_co_id)
            .where(
                or_(
                    and_(Job.Job_type == "PTL", Job.Estimated_start_date.is_not(None)),
                    and_(Job.Job_type != "PTL", Job.Date_assigned.is_not(None)),
                )
            )
            .order_by(effective_date.asc())
            .limit(1)
        )

        job = session.exec(scope_jobs_statement(statement)).first()
        if not job:
            return jsonify({"detail": "No jobs found for this parent company"}), 404

        return jsonify({
            "ID_Jobs":               job.ID_Jobs,
            "Job_type":              job.Job_type,
            "Project_name":          job.Project_name,
            "Project_location":      job.Project_location,
            "Job_status":            job.Job_status,
            "Date_assigned":         job.Date_assigned.isoformat()         if job.Date_assigned         else None,
            "Estimated_start_date":  job.Estimated_start_date.isoformat()  if job.Estimated_start_date  else None,
            "Service_type":          job.Service_type,
            "client": {
                "ID_Client":         job.client.ID_Client,
                "Client_Community":  getattr(job.client, "Client_Community", None),
            } if job.client else None,
        }), 200


@job_bp.get("/<id_job>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
def get_job_by_id(id_job):
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client).selectinload(Client.manager),
                joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.tasks), joinedload(Job.estimate_costs),
                joinedload(Job.payment_units),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.technicians),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.orders).joinedload(Order.financial_docs),
                joinedload(Job.technicians),
                joinedload(Job.building_dept),
                selectinload(Job.comdetails).joinedload(CommissionDetail.comgroup).joinedload(
                    CommissionGroup.commission).joinedload(Commission.member),
                selectinload(Job.financial_docs).options(
                    joinedload(FinancialDocument.order),
                    selectinload(FinancialDocument.financial_doc_items),
                    selectinload(FinancialDocument.financial_transactions)),
                joinedload(Job.subcontractors).joinedload(
                    Subcontractor.orders).joinedload(Order.financial_docs))
            .where(Job.ID_Jobs == id_job)
        )
        obj = session.exec(statement).unique().first()
        if not obj:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        # Portal (sub/tech): solo sus jobs asignados — 404 para no filtrar
        # existencia (REG-037/110/111)
        p_role, p_id = portal_scope()
        if p_role == "subcontractor" and not any(
                s.ID_Subcontractor == p_id for s in obj.subcontractors):
            raise AppException("Job no encontrado.", "job_not_found", 404)
        if p_role == "technician" and not any(
                t.ID_Technician == p_id for t in obj.technicians):
            raise AppException("Job no encontrado.", "job_not_found", 404)

        roles_statement = select(JobMemberLink).where(
            JobMemberLink.job_id == obj.ID_Jobs)
        roles = session.exec(roles_statement).all()
        roles_map = {}
        for link in roles:
            if link.member_id not in roles_map:
                roles_map[link.member_id] = []
            roles_map[link.member_id].append(link.rol)

        # Manager roles for the client
        mgr_roles_map = {}
        if obj.ID_Client:
            mgr_roles_stmt = select(ClientManagerLink).where(ClientManagerLink.clients_id == obj.ID_Client)
            mgr_roles = session.exec(mgr_roles_stmt).all()
            mgr_roles_map = {link.manager_id: link.rol for link in mgr_roles}

        job_data = add_relationships(
            obj, ["client.manager", "members", "multipliers", "building_dept", "change_orders",
                  "attachments", "subcontractors.technicians", "technicians", "tasks",
                  "subcontractors.orders.financial_docs", "estimate_costs", "payment_units",
                  "financial_docs.order", "financial_docs.financial_doc_items",
                  "financial_docs.financial_transactions",
                  "comdetails.comgroup.commission.member"])

        for member in job_data.get("members", []):
            member["rol"] = roles_map.get(member["ID_Member"], [])

        if job_data.get("client") and job_data["client"].get("manager"):
            for mgr in job_data["client"]["manager"]:
                mgr["rol"] = mgr_roles_map.get(mgr["ID_Manager"])

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
    # Antes: `year[-1]` contra `ID_Jobs LIKE 'QID5%'`. Casualmente era la regla
    # correcta, pero sin validar (`?year=abc` construía el patrón `QIDc%`) y
    # sin cubrir los jobs locales, cuyo ID es `QID-I60001` y no casa con `QID6%`.
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        raise AppException(
            f"'year' debe ser un año, no {year!r}.", "invalid_year", 400)
    job_type = job_type.upper()
    with get_session() as session:
        statement = (
            select(Job)
            .options(
                joinedload(Job.client), selectinload(Job.members),
                selectinload(Job.multipliers), selectinload(Job.attachments),
                selectinload(Job.tasks), selectinload(Job.estimate_costs),
                selectinload(Job.payment_units),
                selectinload(Job.subcontractors).selectinload(
                    Subcontractor.technicians),
                selectinload(Job.subcontractors).selectinload(
                    Subcontractor.orders),
                selectinload(Job.tlactivity), selectinload(Job.change_orders),
                joinedload(Job.building_dept))
            .where(Job.Job_type == job_type, expr_anio_app() == year_int)
        )
        # T-27: sin esto, un sub/técnico recibía TODOS los jobs del tipo y año
        # —con su bloque financiero— aunque no estuviera asignado a ninguno.
        # `/jobs/` y `/jobs/<id>` sí lo hacían; este endpoint se quedó fuera del
        # endurecimiento de REG-037/110/111.
        statement = scope_jobs_statement(statement)
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
        # T-27: este endpoint tampoco recortaba a JobReadBasic, así que un rol
        # con solo `job:read_basics` recibía el payload completo.
        policies = getattr(g, "user_policies", [])
        return [serialize_job(j, policies) for j in jobs_data], 200


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
        results = session.exec(scope_jobs_statement(statement)).unique().all()
        if not results:
            return [], 200
        jobs_data = [add_relationships(job, ["client", "members", "multipliers",
                     "attachments", "subcontractors.technicians"]) for job in results]
        policies = getattr(g, "user_policies", [])
        return [serialize_job(j, policies) for j in jobs_data], 200


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
        results = session.exec(scope_jobs_statement(statement)).unique().all()
        if not results:
            return [], 200
        policies = getattr(g, "user_policies", [])
        return [serialize_job(add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]), policies) for job in results], 200


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
        results = session.exec(scope_jobs_statement(statement)).unique().all()
        if not results:
            return [], 200
        policies = getattr(g, "user_policies", [])
        return [serialize_job(add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]), policies) for job in results], 200


@job_bp.get("/by-member-role")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
def get_jobs_by_member_and_role():

    member_id = request.args.get("member_id")
    rol = request.args.get("rol")

    if not member_id:
        raise AppException("member_id es requerido", "missing_params", 400)
    if not rol:
        raise AppException("rol es requerido", "missing_params", 400)

    job_type = request.args.get("type", "").strip().upper() or None
    year_raw = request.args.get("year", "").strip()
    month_raw = request.args.get("month", "").strip().upper()
    page = max(1, int(request.args.get("page",  1)))
    limit = min(200, max(1, int(request.args.get("limit", 50))))

    # Validar y convertir año
    year_int = None
    if year_raw:
        try:
            year_int = int(year_raw)
        except ValueError:
            raise AppException(
                "El parámetro 'year' debe ser un número entero.", "invalid_year", 400)

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
                JobMemberLink.rol == rol,
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
                if year_int is not None:
                    statement = statement.where(
                        extract("year",  date_col) == year_int)
                if month_int is not None:
                    statement = statement.where(
                        extract("month", date_col) == month_int)
            else:
                # Tipo desconocido → OR entre PTL y no-PTL
                from sqlalchemy import and_, or_ as sa_or
                conditions = []
                for jt, col in [("PTL", Job.Estimated_start_date),
                                ("QID", Job.Date_assigned),
                                ("PAR", Job.Date_assigned)]:
                    cond = [Job.Job_type == jt, col.is_not(None)]
                    if year_int is not None:
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
                    JobMemberLink.rol == rol,
                )
                .subquery()
            )
        )
        # (El total sin filtros de fecha/tipo es suficiente para la UI,
        #  pero si quieres el total exacto con todos los filtros, construye
        #  count_stmt con las mismas condiciones que statement arriba.)

        statement = scope_jobs_statement(statement)
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
                "Date_assigned":        j.Date_assigned.isoformat() if j.Date_assigned else None,
                "Estimated_start_date": j.Estimated_start_date.isoformat() if j.Estimated_start_date else None,
                "Gqm_premium_in_money": j.Gqm_premium_in_money,
                "Gqm_target_return":    j.Gqm_target_return,
                "ID_Client":            j.ID_Client,
            }
            for j in results
        ]
        if not PolicyEvaluator.evaluate(getattr(g, "user_policies", []), "job:read"):
            for d in jobs_data:  # job:read_basics: sin claves financieras
                d.pop("Gqm_premium_in_money", None); d.pop("Gqm_target_return", None)

        return jsonify({
            "page":    page,
            "limit":   limit,
            # reemplaza con count real si lo necesitas
            "total":   len(jobs_data),
            "results": jobs_data,
        }), 200


@job_bp.get("/subcontractor/<id_subcontractor>")
@require_permission(["job:read", "job:read_basics"])
@handle_exceptions()
@paginate()
def get_job_by_subcontrID(id_subcontractor):
    # Portal: un sub solo puede pedir SU propio id; un técnico, ninguno (403 y
    # no 404: el id del sub no es secreto, la lista de sus jobs sí).
    p_role, p_id = portal_scope()
    if p_role and id_subcontractor != p_id:
        raise AppException("Forbidden: solo tus propios jobs.", "forbidden", 403)
    with get_session() as session:
        statement = (
            select(Job).join(Job.subcontractors)
            .options(
                joinedload(Job.client), joinedload(Job.members),
                joinedload(Job.multipliers), joinedload(Job.attachments),
                joinedload(Job.subcontractors).joinedload(Subcontractor.technicians))
            .where(Subcontractor.ID_Subcontractor == id_subcontractor)
        )
        results = session.exec(scope_jobs_statement(statement)).unique().all()
        if not results:
            return [], 200
        policies = getattr(g, "user_policies", [])
        return [serialize_job(add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]), policies) for job in results], 200


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
        results = session.exec(scope_jobs_statement(statement)).unique().all()
        if not results:
            return [], 200
        policies = getattr(g, "user_policies", [])
        return [serialize_job(add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]), policies) for job in results], 200


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
        results = session.exec(scope_jobs_statement(statement)).unique().all()
        if not results:
            return [], 200
        policies = getattr(g, "user_policies", [])
        return [serialize_job(add_relationships(job, ["client", "members", "multipliers",
                "attachments", "subcontractors.technicians"]), policies) for job in results], 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
@job_bp.post("/")
@require_permission("job:create")
@handle_exceptions()
@audit("Job created", entity_type="Job", id_from="response")
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
                podio_fields = map_job_to_podio_qid(obj, session=session, year=year)
            elif obj.Job_type == "PTL":
                podio_fields = map_job_to_podio_ptl(obj, session=session, year=year)
            elif obj.Job_type == "PAR":
                podio_fields = map_job_to_podio_par(obj, session=session, year=year)
            else:
                raise AppException(
                    f"Job_type inválido: {obj.Job_type}", "invalid_job_type", 400)

            podio_service = podio_jobs_router.get_service(
                job_type=obj.Job_type, year=year)
            
            try:
                podio_response = podio_service.create_item(podio_fields)

                if not podio_response or not podio_response.get("item_id"):
                    raise AppException(
                        "No se pudo crear el item en Podio (respuesta vacía).", "podio_creation_failed", 502)

                obj.podio_item_id = podio_response["item_id"]
                obj.podio_app_year = year
                item = podio_service.get_item(obj.podio_item_id)
                formatted_id = item.get("app_item_id_formatted")

                if not formatted_id:
                    raise AppException(
                        "No se pudo obtener el ID formateado desde Podio.",
                        "podio_formatted_id_missing", 502)
            except AppException:
                raise
            except Exception as e:
                # Tratar de extraer detalles específicos del error de Podio (ej: pypodio2 TransportException)
                error_details = str(e)
                try:
                    if hasattr(e, 'content') and e.content:
                        import json
                        podio_err = json.loads(e.content)
                        if 'error_description' in podio_err:
                            error_details = f"{error_details} - Detalles: {podio_err['error_description']}"
                        elif 'error_detail' in podio_err:
                            error_details = f"{error_details} - Detalles: {podio_err['error_detail']}"
                    elif hasattr(e, 'response') and hasattr(e.response, 'text') and e.response.text:
                        error_details = f"{error_details} - Detalles: {e.response.text}"
                except Exception:
                    pass # Fallback to default str(e)
                
                raise AppException(
                    f"Error de Podio al crear el registro: {error_details}", "podio_creation_error", 400)

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
            # Un job local no pasa por Podio, asi que nadie le ponia año: se
            # quedaba con podio_app_year NULL y ademas su ID lleva prefijo
            # "QID-I", del que `resolver_anio_app` tampoco puede deducirlo. El
            # resultado era una fila sin año en jobs_table, que obliga al panel
            # a adivinarlo desde las fechas (justo lo que fallaba en 88 jobs).
            if obj.podio_app_year is None:
                obj.podio_app_year = year or (
                    obj.Date_assigned.year if obj.Date_assigned else date.today().year)

        # Fix race condition: Webhook may have already inserted this job
        existing = session.exec(select(Job).where(Job.ID_Jobs == obj.ID_Jobs)).first()
        if existing:
            logger.info(f"⚠️ El webhook ya insertó el Job {obj.ID_Jobs}. Actualizando registro existente.")
            for key, value in obj.model_dump(exclude_unset=True).items():
                if key not in ["id", "ID_Jobs", "created_at", "updated_at"] and value is not None:
                    setattr(existing, key, value)
            save_with_retry(session, existing)
            obj = existing
        else:
            try:
                # Intento de insert único, por si el webhook lo inserta en este exacto milisegundo
                save_with_retry(session, obj, max_retries=1)
            except Exception as e:
                # Si falló, muy probablemente fue un IntegrityError (duplicate key) por el webhook
                existing_after = session.exec(select(Job).where(Job.ID_Jobs == obj.ID_Jobs)).first()
                if existing_after:
                    logger.info(f"⚠️ El webhook ganó la carrera para {obj.ID_Jobs}. Recuperando y actualizando.")
                    for key, value in obj.model_dump(exclude_unset=True).items():
                        if key not in ["id", "ID_Jobs", "created_at", "updated_at"] and value is not None:
                            setattr(existing_after, key, value)
                    save_with_retry(session, existing_after)
                    obj = existing_after
                else:
                    # Compensación (REG-013): el item ya existe en Podio pero el
                    # guardado local falló de verdad → borrar el item remoto
                    # para no dejar un huérfano (mismo patrón que Order.py).
                    if sync_podio and obj.podio_item_id:
                        try:
                            podio_service.delete_item(obj.podio_item_id)
                            logger.warning(
                                "Compensación: item %s eliminado de Podio tras fallo del guardado local",
                                obj.podio_item_id)
                        except Exception:
                            logger.exception(
                                "Compensación fallida: item %s queda huérfano en Podio",
                                obj.podio_item_id)
                            from src.utils.failed_sync import record_failed_sync
                            record_failed_sync(
                                session,
                                item_id=obj.podio_item_id,
                                hook_type="create_job_compensation",
                                payload={"job_id": obj.ID_Jobs, "job_type": obj.Job_type,
                                         "year": year},
                                error=e,
                            )
                    raise e
        # ── Recálculo automático de campos derivados ──────────────────────
        # Sin esto el job nace con TODOS los agregados en None/0 y no se
        # rellenan hasta el primer PATCH o hasta que vuelva el webhook de Podio
        # (que en un alta sin sync_podio no llega nunca). Mismo patrón que el
        # PATCH de más abajo.
        recalculate_and_apply(obj.ID_Jobs, session)
        session.commit()
        session.refresh(obj)
        # ─────────────────────────────────────────────────────────────────

        logger.info("✅ Job creado | job_id=%s | podio_item_id=%s",
                    obj.ID_Jobs, obj.podio_item_id)
        return obj.model_dump(), 201


@job_bp.patch("/<id_job>")
@require_permission("job:update")
@handle_exceptions()
@audit("Job updated", entity_type="Job", id_param="id_job")
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
            if year is None:
                # Sin ?year explícito: usar el año persistido del job (REG-015)
                from src.utils.podio_job_sync import resolve_job_app_year
                year = resolve_job_app_year(obj)
            if obj.Job_type == "QID":
                podio_fields = map_job_to_podio_qid(obj, session=session, year=year)
            elif obj.Job_type == "PTL":
                podio_fields = map_job_to_podio_ptl(obj, session=session, year=year)
            elif obj.Job_type == "PAR":
                podio_fields = map_job_to_podio_par(obj, session=session, year=year)
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
            except Exception as podio_err:
                # REG-070: el cambio local YA está commiteado — registrar la
                # divergencia para reconciliar (lista/resync de failed_syncs)
                # y decirlo explícitamente en la respuesta, no un 502 opaco.
                logger.exception("❌ Error actualizando Job en Podio | job_id=%s | podio_item_id=%s",
                                 id_job, obj.podio_item_id)
                from src.utils.failed_sync import record_failed_sync
                record_failed_sync(
                    session,
                    item_id=obj.podio_item_id,
                    hook_type="update_job_divergence",
                    payload={"job_id": id_job, "job_type": obj.Job_type,
                             "year": year},
                    error=podio_err,
                )
                raise AppException(
                    "El Job se guardó localmente pero NO se sincronizó a Podio "
                    "(divergencia registrada en failed_syncs; reintenta el "
                    "update o usa el resync).",
                    "podio_update_failed_local_saved", 502)

        return obj.model_dump(), 200


@job_bp.delete("/<id_job>")
@require_permission("job:delete")
@handle_exceptions()
def delete_job(id_job):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    force = request.args.get("force", "false").lower() == "true"

    from src.models.ChangeOrderModel import ChangeOrder
    from src.models.FinancialDocModel import FinancialDocument
    from src.models.OrderModel import Order

    with get_session() as session:
        obj = session.exec(select(Job).where(Job.ID_Jobs == id_job)).first()
        if not obj:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        # REG-014: el delete por API dejaba Orders/COs/FinancialDocs huérfanos
        # (Order ni siquiera tiene FK a Job — solo job_podio_id).
        podio_ref = str(obj.podio_item_id) if obj.podio_item_id else None
        orders = session.exec(select(Order).where(
            Order.job_podio_id == podio_ref)).all() if podio_ref else []

        # COs y findocs cuelgan por TRES vías (job_podio_id, ID_Order, ID_Jobs):
        # recogerlos solo por podio_ref dejaba huérfano el CO enlazado a una
        # Order, y su FK bloqueaba el DELETE de esa Order.
        _order_ids = [o.ID_Order for o in orders if o.ID_Order]
        co_conds = [ChangeOrder.ID_Jobs == id_job]
        fd_conds = [FinancialDocument.ID_Jobs == id_job]
        if podio_ref:
            co_conds.append(ChangeOrder.job_podio_id == podio_ref)
        if _order_ids:
            co_conds.append(ChangeOrder.ID_Order.in_(_order_ids))
            fd_conds.append(FinancialDocument.ID_Order.in_(_order_ids))
        change_orders = session.exec(
            select(ChangeOrder).where(or_(*co_conds))).all()
        fin_docs = session.exec(
            select(FinancialDocument).where(or_(*fd_conds))).all()

        if orders or change_orders or fin_docs:
            if not force:
                raise AppException(
                    f"El job tiene registros vinculados: {len(orders)} orders, "
                    f"{len(change_orders)} change orders, {len(fin_docs)} documentos "
                    "financieros. Repite con ?force=true (requiere permiso "
                    "job:force_delete) para borrarlos en cascada.",
                    "job_has_children", 409)

            from src.utils.middleware.auth.routes_protection import get_user_context
            from src.utils.policy_evaluator import PolicyEvaluator
            _, _, policies = get_user_context()
            if not PolicyEvaluator.evaluate(policies, "job:force_delete", "*"):
                raise AppException(
                    "?force=true requiere el permiso job:force_delete.",
                    "forbidden", 403)

            # EstimateCost/Opportunities referencian order.ID_Order sin
            # ondelete: desenlazar primero o el DELETE de la Order viola FK.
            # (Los EstimateCost del propio job caen luego con su cascade.)
            # Todo en SQL bulk: idempotente y sin StaleDataError si el webhook
            # de Podio borró lo mismo en paralelo (ver Webhook_bp).
            from sqlalchemy import update as sa_update
            from sqlmodel import delete as sq_delete

            order_ids = [o.ID_Order for o in orders if o.ID_Order]
            if order_ids:
                from src.models.EstimateCostModel import EstimateCost
                from src.models.OpportunitiesModel import Opportunities
                for model in (EstimateCost, Opportunities):
                    session.exec(sa_update(model).where(
                        model.ID_Order.in_(order_ids)).values(ID_Order=None))

            co_ids = [c.ID_ChangeOrder for c in change_orders if c.ID_ChangeOrder]
            if co_ids:
                session.exec(sq_delete(ChangeOrder).where(
                    ChangeOrder.ID_ChangeOrder.in_(co_ids)))
            fd_ids = [f.ID_FinancialDoc for f in fin_docs if f.ID_FinancialDoc]
            if fd_ids:
                session.exec(sq_delete(FinancialDocument).where(
                    FinancialDocument.ID_FinancialDoc.in_(fd_ids)))
            if order_ids:
                session.exec(sq_delete(Order).where(
                    Order.ID_Order.in_(order_ids)))
            session.expire_all()  # colecciones cacheadas ya no reflejan la BD
            logger.warning(
                "🗑️ Cascada forzada de Job %s: %s orders, %s COs, %s findocs",
                id_job, len(orders), len(change_orders), len(fin_docs))

        if sync_podio and obj.podio_item_id:
            if year is None:
                from src.utils.podio_job_sync import resolve_job_app_year
                year = resolve_job_app_year(obj)
            podio_service = podio_jobs_router.get_service(
                job_type=obj.Job_type, year=year)
            import requests
            try:
                podio_service.delete_item(int(obj.podio_item_id))
                register_event(obj.podio_item_id)
                logger.info("🗑️ Job eliminado en Podio | job_id=%s | podio_item_id=%s",
                            id_job, obj.podio_item_id)
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else None
                if status_code in (403, 404, 410):
                    logger.warning("⚠️ No se pudo eliminar el item en Podio (Status %s) - Procediendo con eliminación local | job_id=%s | podio_item_id=%s",
                                   status_code, id_job, obj.podio_item_id)
                else:
                    logger.exception("❌ Error eliminando Job en Podio | job_id=%s | podio_item_id=%s",
                                     id_job, obj.podio_item_id)
                    raise AppException(
                        "Error al eliminar el Job en Podio.", "podio_delete_failed", 502)
            except Exception:
                logger.exception("❌ Error inesperado eliminando Job en Podio | job_id=%s | podio_item_id=%s",
                                 id_job, obj.podio_item_id)
                raise AppException(
                    "Error al eliminar el Job en Podio.", "podio_delete_failed", 502)

        # Workaround para evitar StaleDataError por duplicados en las tablas de links
        session.exec(delete(JobMemberLink).where(JobMemberLink.job_id == id_job))
        session.exec(delete(JobMultiplierRLink).where(JobMultiplierRLink.job_id == id_job))
        session.exec(delete(JobSubcontractorLink).where(JobSubcontractorLink.job_id == id_job))
        session.exec(delete(JobTechnicianLink).where(JobTechnicianLink.job_id == id_job))
        session.exec(delete(JobPaymentULink).where(JobPaymentULink.job_id == id_job))

        delete_with_retry(session, obj)
        logger.info("🗑️ Job eliminado | job_id=%s", id_job)
        return jsonify({"message": f"Job {id_job} eliminado correctamente"}), 200


# --------------- RUTA PARA EXPORTAR EXCEL ----------#
# Blueprint de Jobs:
job_excel_bp = Blueprint("job_excel_blueprint",
                         __name__, url_prefix="/jobs_excel")


@job_excel_bp.post("/export")
@require_permission("job:read")  # el Excel lleva columnas financieras: nunca con solo read_basics  # REG-021: reactivado
@handle_exceptions()
def export_jobs_excel():
    data = request.get_json(force=True) or {}
    payload = JobExportRequest.model_validate(data)

    with get_session() as session:
        excel_bytes = generate_jobs_excel(session=session, request=payload)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"jobs_export_{timestamp}.xlsx"

    return send_file(
        io.BytesIO(excel_bytes),
        mimetype=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        as_attachment=True,
        download_name=filename,
    )
