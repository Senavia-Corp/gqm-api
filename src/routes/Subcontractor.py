from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.SubcontractorModel import Subcontractor, SubcontractorCreate, SubcontractorUpdate
from ..models.SkillsModel import Skills
from ..models.TechnicianModel import Technician
from ..models.OrderModel import Order
from ..models.ChangeOrderModel import ChangeOrder
from ..models.FinancialDocModel import FinancialDocument
from ..models.EstimateCostModel import EstimateCost
from ..models.link_models.JobSubcontractor import JobSubcontractorLink
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload, load_only
from sqlalchemy import func, or_
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.subcontractor_services import podio_subc_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.subcontractor_mapper import map_subc_to_podio
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.audit import audit
from src.utils.middleware.auth.routes_protection import require_permission
from src.utils.middleware.auth.password_hashing import hash_password


# Blueprint de Subcontractor
subcontractor_bp = Blueprint(
    "subcontractor_blueprint", __name__, url_prefix="/subcontractors")


# -------------------RUTAS CRUD-------------------#

# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los subcontratistas
@subcontractor_bp.get("/")
@require_permission("subcontractor:read")
@handle_exceptions()
@paginate()
def list_subcontractors():

    with get_session() as session:
        statement = (
            select(Subcontractor)
            .options(
                joinedload(Subcontractor.technicians)
                .joinedload(Technician.tasks),
                joinedload(Subcontractor.orders),
                joinedload(Subcontractor.jobs),
                joinedload(Subcontractor.attachments),
                joinedload(Subcontractor.role),
                joinedload(Subcontractor.tlactivity),
                joinedload(Subcontractor.skills),
                joinedload(Subcontractor.opportunities),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        subcontr_data = [
            add_relationships(
                subcontractor, ["technicians.tasks", "orders", "jobs", "attachments",
                                "role", "tlactivity", "skills", "opportunities"])
            for subcontractor in results]

        return subcontr_data, 200


@subcontractor_bp.get("/subcontractors_table")
@require_permission("subcontractor:read")
@handle_exceptions()
def list_subcontractors_table():
    """
    Endpoint ligero para la tabla de subcontractors.
    Soporta paginación server-side, filtro por status y búsqueda global.

    Query params:
        page   (int,  default 1)
        limit  (int,  default 10, max 200)
        status (str,  optional) — filtro exacto por Status
        q      (str,  optional) — búsqueda global contra Name, Organization,
                                  Email_Address, Specialty, ID_Subcontractor
    """
    page = max(1, int(request.args.get("page",  1)))
    limit = min(200, max(1, int(request.args.get("limit", 10))))
    status = request.args.get("status", "").strip() or None
    q = request.args.get("q", "").strip()
    skills_query = request.args.get("skills", "").strip()
    exclude_job_id = request.args.get("exclude_job_id", "").strip()

    with get_session() as session:

        # ── Base statement ─────────────────────────────────────────────────
        stmt = (
            select(Subcontractor)
            .options(
                joinedload(Subcontractor.skills).load_only(Skills.ID_Skill)
            )
        )

        # ── Filtro por Status ──────────────────────────────────────────────
        if status:
            stmt = stmt.where(Subcontractor.Status == status)

        # ── Búsqueda global ────────────────────────────────────────────────
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Subcontractor.ID_Subcontractor.ilike(pattern),
                    Subcontractor.Name.ilike(pattern),
                    Subcontractor.Organization.ilike(pattern),
                    Subcontractor.Email_Address.ilike(pattern),
                    Subcontractor.Specialty.ilike(pattern),
                )
            )

        # ── Filtro por Skills ──────────────────────────────────────────────
        if skills_query:
            skill_ids = [s.strip() for s in skills_query.split(",") if s.strip()]
            if skill_ids:
                stmt = stmt.where(Subcontractor.skills.any(Skills.ID_Skill.in_(skill_ids)))

        # ── Excluir vinculados a un Job ──────────────────────────────────
        if exclude_job_id:
            linked_subquery = (
                select(JobSubcontractorLink.subcontr_id)
                .where(JobSubcontractorLink.job_id == exclude_job_id)
            )
            stmt = stmt.where(Subcontractor.ID_Subcontractor.not_in(linked_subquery))

        # ── Total ──────────────────────────────────────────────────────────
        count_stmt = select(func.count(Subcontractor.ID_Subcontractor.distinct())).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()

        # ── Paginación SQL ─────────────────────────────────────────────────
        offset = (page - 1) * limit
        stmt = stmt.order_by(Subcontractor.ID_Subcontractor.desc()).offset(
            offset).limit(limit)
        results = session.exec(stmt).unique().all()

        # ── Serializar ─────────────────────────────────────────────────────
        rows = [
            {
                "ID_Subcontractor": s.ID_Subcontractor,
                "Name":             s.Name,
                "Organization":     s.Organization,
                "Status":           s.Status,
                "Email_Address":    s.Email_Address,
                "Phone_Number":     s.Phone_Number,
                "Gqm_compliance":   s.Gqm_compliance,
                "Specialty":        s.Specialty,
                "skill_ids":        [sk.ID_Skill for sk in s.skills],
                "podio_item_id":    s.podio_item_id,
            }
            for s in results
        ]

        return {
            "page":    page,
            "limit":   limit,
            "total":   total,
            "results": rows,
        }, 200


# Ruta para conseguir un subcontratista por ID
@subcontractor_bp.get("/<id_subcontractor>")
@require_permission("subcontractor:read")
@handle_exceptions()
def get_subcontractor(id_subcontractor):

    with get_session() as session:
        statement = (
            select(Subcontractor)
            .options(
                joinedload(Subcontractor.technicians)
                .joinedload(Technician.tasks),
                joinedload(Subcontractor.tasks),
                joinedload(Subcontractor.orders).joinedload(Order.change_orders),
                joinedload(Subcontractor.orders).joinedload(Order.financial_docs),
                joinedload(Subcontractor.orders).joinedload(Order.estimate_costs),
                joinedload(Subcontractor.jobs),
                joinedload(Subcontractor.attachments),
                joinedload(Subcontractor.role),
                joinedload(Subcontractor.tlactivity),
                joinedload(Subcontractor.skills),
                joinedload(Subcontractor.opportunities),
                joinedload(Subcontractor.certificates)
            )
            .where(Subcontractor.ID_Subcontractor == id_subcontractor)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Subcontractor no encontrado.",
                               "subc_not_found", 404)

        subcontr_data = add_relationships(
            obj, ["technicians.tasks", "tasks",
                  "orders.change_orders", "orders.financial_docs", "orders.estimate_costs",
                  "jobs", "attachments",
                  "role", "tlactivity", "skills", "opportunities", "certificates"])

        return subcontr_data, 200


# Ruta para conseguir un subcontratista por estado
@subcontractor_bp.get("/status/<status>")
@require_permission("subcontractor:read")
@handle_exceptions()
@paginate()
def list_subcontractor_by_state(status):

    with get_session() as session:
        statement = (
            select(Subcontractor)
            .options(
                joinedload(Subcontractor.technicians)
                .joinedload(Technician.tasks),
                joinedload(Subcontractor.orders),
                joinedload(Subcontractor.jobs),
                joinedload(Subcontractor.attachments),
            )
            .where(Subcontractor.Status == status)
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        subcontr_data = [
            add_relationships(
                subcontr, ["technicians.tasks", "orders", "jobs", "attachments"])
            for subcontr in results
        ]

        return subcontr_data, 200


# Ruta para conseguir un subcontratista por GQM compliance
@subcontractor_bp.get("/compliance/<compliance>")
@require_permission("subcontractor:read")
@handle_exceptions()
@paginate()
def list_subc_by_gqm_compliance(compliance):

    with get_session() as session:
        statement = (
            select(Subcontractor)
            .options(
                joinedload(Subcontractor.technicians)
                .joinedload(Technician.tasks),
                joinedload(Subcontractor.orders),
                joinedload(Subcontractor.jobs),
                joinedload(Subcontractor.attachments),
            )
            .where(Subcontractor.Gqm_compliance == compliance)
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        subcontr_data = [
            add_relationships(
                subcontr, ["technicians.tasks", "orders", "jobs", "attachments"])
            for subcontr in results
        ]

        return subcontr_data, 200


# Ruta para conseguir un subcontratista por GQM best service training
@subcontractor_bp.get("/bts/<bts>")
@require_permission("subcontractor:read")
@handle_exceptions()
@paginate()
def list_subcontractor_by_gqm_bts(bts):

    with get_session() as session:
        statement = (
            select(Subcontractor)
            .options(
                joinedload(Subcontractor.technicians)
                .joinedload(Technician.tasks),
                joinedload(Subcontractor.orders),
                joinedload(Subcontractor.jobs),
                joinedload(Subcontractor.attachments),
            )
            .where(Subcontractor.Gqm_best_service_training == bts)
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        subcontr_data = [
            add_relationships(
                subcontr, ["technicians.tasks", "orders", "jobs", "attachments"])
            for subcontr in results
        ]

        return subcontr_data, 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un subcontratista
@subcontractor_bp.post("/")
@require_permission("subcontractor:create")
@handle_exceptions()
@audit("Subcontractor created", entity_type="Subcontractor", id_from="response")
def create_subcontractor():

    data = request.get_json()
    create_subcontractor = SubcontractorCreate.model_validate(data)
    obj = Subcontractor(
        **create_subcontractor.model_dump(exclude_unset=False, exclude_none=False))
        
    if obj.Password:
        obj.Password = hash_password(obj.Password)

    # 🔘 Función de sincronización
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Subcontractor, "ID_Subcontractor", "SUBC")
        obj.ID_Subcontractor = new_id

        # ----------- 🟢 CREAR EN PODIO (SI APLICA)
        if sync_podio:

            podio_fields = map_subc_to_podio(obj)
            podio_service = podio_subc_router.get_service()
            podio_response = podio_service.create_item(podio_fields)

            if not podio_response or not podio_response.get("item_id"):
                raise AppException(
                    "No se pudo crear el item en Podio.", "podio_creation_failed", 502)

            # Guardar el podio_item_id en PostgreSQL
            obj.podio_item_id = podio_response["item_id"]

            # Anti-loop: registrar evento
            register_event(obj.podio_item_id)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Subcontractor creado | subc_id=%s | podio_item_id=%s",
            obj.ID_Subcontractor,
            obj.podio_item_id
        )

        response = obj.model_dump()
        response.pop("Password", None)
        return response, 201


# Ruta para actualizar un subcontratista
@subcontractor_bp.patch("/<subc_id>")
@require_permission("subcontractor:update")
@handle_exceptions()
@audit("Subcontractor updated", entity_type="Subcontractor", id_param="subc_id")
def update_subcontractor(subc_id):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    data = request.get_json()

    with get_session() as session:
        obj = session.exec(
            select(Subcontractor).where(
                Subcontractor.ID_Subcontractor == subc_id)
        ).first()
        if not obj:
            raise AppException("Subcontractor no encontrado.",
                               "subc_not_found", 404)

        update_subcontractor = SubcontractorUpdate.model_validate(data)
        update_data_dict = update_subcontractor.model_dump(exclude_unset=True)

        if "Password" in update_data_dict and update_data_dict["Password"]:
            update_data_dict["Password"] = hash_password(update_data_dict["Password"])

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        logger.info("🔄 Subcontractor actualizado | subc_id=%s", subc_id)

        # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:
            podio_service = podio_subc_router.get_service()
            podio_fields = map_subc_to_podio(obj)

            try:
                podio_service.update_item(
                    int(obj.podio_item_id), podio_fields)

                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🔄 Subcontractor actualizado en Podio | subc_id=%s | podio_item_id=%s",
                    subc_id,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error actualizando Subcontractor en Podio | subc_id=%s | podio_item_id=%s",
                    subc_id,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al actualizar el Subcontractor en Podio.",
                    "podio_update_failed",
                    502
                )

        response = obj.model_dump()
        response.pop("Password", None)
        return response, 200


# Ruta para eliminar un subcontratista
@subcontractor_bp.delete("/<subc_id>")
@require_permission("subcontractor:delete")
@handle_exceptions()
@audit("Subcontractor deleted", entity_type="Subcontractor", id_param="subc_id")
def delete_subcontractor(subc_id):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:
        obj = session.exec(select(Subcontractor).where(
            Subcontractor.ID_Subcontractor == subc_id)).first()
        if not obj:
            raise AppException("Subcontractor no encontrado.",
                               "subc_not_found", 404)

        # ----------- 🟢 BORRAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:

            podio_service = podio_subc_router.get_service()

            try:
                podio_service.delete_item(int(obj.podio_item_id))
                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🗑️ Subcontractor eliminado en Podio | subc_id=%s | podio_item_id=%s",
                    subc_id,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error eliminando Subcontractor en Podio | subc_id=%s | podio_item_id=%s",
                    subc_id,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al eliminar el Subcontractor en Podio.",
                    "podio_delete_failed",
                    502
                )

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ Subcontractor eliminado | subc_id=%s",
            subc_id
        )

        return jsonify({
            "message": f"Subcontractor {subc_id} eliminado correctamente"
        }), 200
