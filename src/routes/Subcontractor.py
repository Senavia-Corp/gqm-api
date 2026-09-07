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
from sqlalchemy import func, or_, false
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.subcontractor_services import podio_subc_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.subcontractor_mapper import map_subc_to_podio
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.audit import audit
from src.utils.middleware.auth.routes_protection import require_permission, self_profile_guard, portal_scope, portal_owns_subcontractor
from src.utils.middleware.auth.password_hashing import hash_password
from src.utils.password_policy import validar_password, PasswordDebil


# Blueprint de Subcontractor
subcontractor_bp = Blueprint(
    "subcontractor_blueprint", __name__, url_prefix="/subcontractors")


def _acotar_a_portal(statement):
    """P-05: acota un listado de subcontratistas a lo que el llamante puede ver.

    Los cinco listados de este fichero (`/`, `/subcontractors_table`,
    `/status/<s>`, `/compliance/<c>` y `/bts/<b>`) devolvían el censo completo
    de subcontratistas a cualquiera con `subcontractor:read`, y la política
    `subcontractor-portal` lo concede. Decisión ratificada del cliente
    (ambigüedad 5): un sub no ve NADA de otro sub, así que solo se ve a sí mismo.

    El filtro va en el statement y no sobre la lista ya construida porque
    @paginate calcula `total` con lo que devolvemos y `/subcontractors_table`
    hace su COUNT sobre este mismo statement: acotando antes, el total no
    delata cuántos subcontratistas hay.

    El staff (full_admin, gqm_member) sale por `rol is None` y no cambia.
    """
    rol, uid = portal_scope()
    if rol == "subcontractor":
        return statement.where(Subcontractor.ID_Subcontractor == uid)
    if rol == "technician":
        # Hoy inalcanzable —`subcontractor:read` no está en `technical-portal`,
        # así que @require_permission corta antes con 403— pero si algún día se
        # le concediera, un técnico tampoco debe enumerar subcontratistas.
        return statement.where(false())
    return statement


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

        # P-05: sin esto el listado entregaba a un sub la ficha de todos los
        # demás, con sus `technicians` y las tareas de éstos. Ver _acotar_a_portal.
        statement = _acotar_a_portal(statement)

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

        # P-05: recorte de portal antes que cualquier otro filtro, para que el
        # COUNT de más abajo cuente solo lo propio. Ver _acotar_a_portal.
        stmt = _acotar_a_portal(stmt)

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
        # El COUNT se hace SOBRE LA SUBCONSULTA, no sobre la tabla base.
        #
        # Estaba escrito como
        #     select(func.count(Subcontractor.ID_Subcontractor.distinct()))
        #         .select_from(stmt.subquery())
        # y eso genera `count(DISTINCT subcontractor."ID_Subcontractor")
        # FROM (subconsulta) , subcontractor` — un producto cartesiano con la
        # tabla base. El resultado: el `total` ignoraba TODOS los filtros.
        #
        # Con el recorte de portal recien puesto quedaba a la vista: un
        # subcontratista recibia sus propias filas (ids=['SUBC60001']) y
        # `total: 2`, es decir el CENSO GLOBAL de subcontratistas de GQM. Un
        # numero es poca cosa hasta que es el numero de contratistas de tu
        # competencia. Tambien falseaba la paginacion para el staff con
        # cualquier filtro (`?status=`, `?q=`).
        subconsulta = stmt.subquery()
        count_stmt = select(
            func.count(func.distinct(subconsulta.c.ID_Subcontractor))
        ).select_from(subconsulta)
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

        # P-05: esta ruta no comprobaba pertenencia, así que un sub leía la ficha
        # completa de otro —sus `orders`, sus `technicians` y las tareas de
        # éstos— y el panel la montaba entera por URL directa (U-03).
        # 404 y no 403: para un rol de portal un 403 confirmaría que el id
        # existe y dejaría la ruta enumerable. Es la convención de esta base de
        # código (Job.py:506-507) y el modismo de Tasks.py:170.
        if not obj or not portal_owns_subcontractor(id_subcontractor):
            raise AppException("Subcontractor no encontrado.",
                               "subc_not_found", 404)

        relaciones = ["technicians.tasks", "tasks",
                      "orders.change_orders", "orders.financial_docs", "orders.estimate_costs",
                      "jobs", "attachments",
                      "role", "tlactivity", "skills", "opportunities", "certificates"]

        # P-05 (segunda mitad): `orders` y lo que cuelga de ellas no salen a
        # portal NI SOBRE LA FICHA PROPIA. El PR #116 le retiró `finance:read`
        # al sub porque «las finanzas no tienen scoping de portal»; entregarle
        # las órdenes, sus documentos financieros y sus costes estimados
        # embebidos en su propia ficha contradiría esa decisión y sería la
        # puerta de atrás al mismo dato. El staff recibe la expansión completa.
        # El resto de la ficha se mantiene: es la landing del sub en el panel.
        rol_portal, _ = portal_scope()
        if rol_portal:
            relaciones = [r for r in relaciones if not r.startswith("orders")]

        subcontr_data = add_relationships(obj, relaciones)

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

        # P-05: el filtro por estado no eximía del scoping — un sub podía barrer
        # el censo entero estado a estado. Ver _acotar_a_portal.
        statement = _acotar_a_portal(statement)

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

        # P-05: idem — y aquí el barrido devolvía además el `Gqm_compliance`
        # ajeno, que es F-04. Ver _acotar_a_portal.
        statement = _acotar_a_portal(statement)

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

        # P-05: idem. Ver _acotar_a_portal.
        statement = _acotar_a_portal(statement)

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
        # O-01: hasta aquí "1", "abc" y "password" devolvían 201. Se valida en
        # SERVIDOR porque el alta la teclea un administrador y esa contraseña es
        # la definitiva: una comprobación solo en el panel no protege de un curl
        # ni del alta masiva de los 432 subcontratistas. El hasheo no cambia.
        try:
            validar_password(obj.Password)
        except PasswordDebil as debil:
            raise AppException(str(debil), "weak_password", 400)

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

        # REG-142: bienvenida/alta (no bloqueante)
        try:
            from src.services.email_service import send_welcome
            if obj.Email_Address:
                send_welcome(obj.Email_Address, obj.Name or obj.Organization or "there")
        except Exception:
            pass

        return response, 201


# Ruta para actualizar un subcontratista
@subcontractor_bp.patch("/<subc_id>")
@require_permission(["subcontractor:update", "profile:update_own"])
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
        # Autoservicio: sin subcontractor:update solo su propio registro,
        # sin campos privilegiados (ID_Role/Active).
        update_data_dict = self_profile_guard(
            "subcontractor", subc_id, update_data_dict)

        if "Password" in update_data_dict and update_data_dict["Password"]:
            # O-01: misma política que en el alta. El PATCH era la otra puerta
            # sin validar, incluida la del propio sub vía `profile:update_own`
            # (self_profile_guard deja pasar `Password`: no es campo privilegiado).
            try:
                validar_password(update_data_dict["Password"])
            except PasswordDebil as debil:
                raise AppException(str(debil), "weak_password", 400)

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
