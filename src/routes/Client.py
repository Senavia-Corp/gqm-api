# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ClientModel import Client, ClientCreate, ClientUpdate
from ..models.JobModel import Job
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import load_only as _load_only
from sqlalchemy import func, or_, and_, extract
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.client_services import podio_clients_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.client_mapper import map_client_to_podio
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.audit import audit
from src.utils.middleware.auth.routes_protection import require_permission

# Blueprint de Client:
client_bp = Blueprint("client_blueprint", __name__, url_prefix="/clients")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los clientes
@client_bp.get("/")
@require_permission("client:read")
@handle_exceptions()
@paginate()
def list_clients():

    with get_session() as session:
        # Trae todos los clientes con sus jobs
        statement = (
            select(Client)
            .options(
                joinedload(Client.jobs),
                joinedload(Client.manager),
                joinedload(Client.parent_mgmt_co),
                joinedload(Client.standard_ps),
                joinedload(Client.members),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        clients_data = [
            add_relationships(
                client, ["jobs", "manager", "parent_mgmt_co", "standard_ps", "members"])
            for client in results]

        return clients_data, 200


@client_bp.get("/table")
@require_permission("client:read")
@handle_exceptions()
def list_clients_table():
    """
    Endpoint ligero para la tabla de comunidades.
    NO carga relaciones (jobs, managers, members, parent_mgmt_co).
    Solo devuelve las columnas necesarias para renderizar la tabla.

    Query params:
        page   (int,  default 1)
        limit  (int,  default 20, max 200)
        q      (str,  optional) — búsqueda global contra múltiples columnas
    """
    page = max(1, int(request.args.get("page",  1)))
    limit = min(200, max(1, int(request.args.get("limit", 20))))
    q = request.args.get("q", "").strip()

    with get_session() as session:

        # ── Base statement ────────────────────────────────────────────────────
        # load_only hace que SQLAlchemy solo emita SELECT de esas columnas,
        # sin disparar lazy loads ni joins de relaciones.
        stmt = (
            select(Client)
            .options(
                _load_only(
                    Client.ID_Client,
                    Client.Client_Community,
                    Client.Address,
                    Client.Email_Address,
                    Client.Phone_Number,
                    Client.Client_Status,
                    Client.Compliance_Partner,
                    Client.ID_Community_Tracking,
                    Client.podio_item_id,
                )
            )
        )

        # ── Filtro de búsqueda global ─────────────────────────────────────────
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Client.ID_Client.ilike(pattern),
                    Client.Client_Community.ilike(pattern),
                    Client.Address.ilike(pattern),
                    Client.Compliance_Partner.ilike(pattern),
                    Client.Client_Status.ilike(pattern),
                    Client.ID_Community_Tracking.ilike(pattern),
                )
            )

        # ── Total (para paginación frontend) ──────────────────────────────────
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()

        # ── Paginación SQL (solo trae la página pedida) ───────────────────────
        offset = (page - 1) * limit
        stmt = stmt.order_by(Client.ID_Client.desc()
                             ).offset(offset).limit(limit)
        results = session.exec(stmt).all()

        # ── Serializar manualmente ────────────────────────────────────────────
        # NO usar model_dump() aquí: dispara lazy loads de relaciones.
        rows = []
        for c in results:
            rows.append({
                "ID_Client":             c.ID_Client,
                "Client_Community":      c.Client_Community,
                "Address":               c.Address,
                "Email_Address":         c.Email_Address,   # JSON list or None
                "Phone_Number":          c.Phone_Number,    # JSON list or None
                "Client_Status":         c.Client_Status,
                "Compliance_Partner":    c.Compliance_Partner,
                "ID_Community_Tracking": c.ID_Community_Tracking,
                "podio_item_id":         c.podio_item_id,
            })

        return {
            "page":    page,
            "limit":   limit,
            "total":   total,
            "results": rows,
        }, 200


# Ruta para conseguir un cliente por ID
@client_bp.get("/<id_client>")
@require_permission("client:read")
@handle_exceptions()
def get_client(id_client):

    with get_session() as session:
        statement = (
            select(Client)
            .options(
                joinedload(Client.jobs),
                joinedload(Client.manager),
                joinedload(Client.parent_mgmt_co),
                joinedload(Client.standard_ps),
                joinedload(Client.members),
            )
            .where(Client.ID_Client == id_client)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Client no encontrado.",
                               "client_not_found", 404)

        client_data = add_relationships(
            obj, ["jobs", "manager", "parent_mgmt_co", "standard_ps", "members"])

        return client_data, 200


@client_bp.get("/<id_client>/metrics")
@require_permission("client:read")
@handle_exceptions()
def get_client_metrics(id_client):
    """
    Returns performance metrics for a community/client.

    Query params:
        month (int, 1-12): optional month filter
        year  (int):       optional year filter
    When both are omitted, returns all-time totals.
    """
    month_str = request.args.get("month", "").strip()
    year_str  = request.args.get("year",  "").strip()

    month = int(month_str) if month_str.isdigit() and 1 <= int(month_str) <= 12 else None
    year  = int(year_str)  if year_str.isdigit()  and 1900 <= int(year_str) <= 2100 else None

    PROPOSALS_STATUSES   = {"Waiting for Approval"}
    EXCLUDE_FROM_APPROVED = {"Assigned/P. Quote", "Waiting for Approval", "Cancelled"}
    INPROGRESS_STATUSES  = {"Scheduled / Work in Progress", "Assigned-In progress", "Invoiced", "In Progress"}
    PAID_STATUSES        = {"paid"}   # compared after .upper()

    with get_session() as session:
        base = select(Job).where(Job.ID_Client == id_client)

        if year is not None or month is not None:
            ptl_conditions  = [Job.Job_type == "PTL", Job.Estimated_start_date.is_not(None)]
            nonptl_conditions = [Job.Job_type != "PTL", Job.Date_assigned.is_not(None)]
            if year is not None:
                ptl_conditions.append(extract("year", Job.Estimated_start_date) == year)
                nonptl_conditions.append(extract("year", Job.Date_assigned) == year)
            if month is not None:
                ptl_conditions.append(extract("month", Job.Estimated_start_date) == month)
                nonptl_conditions.append(extract("month", Job.Date_assigned) == month)
            base = base.where(
                or_(and_(*ptl_conditions), and_(*nonptl_conditions))
            )

        jobs = session.exec(base).all()

        proposals   = 0
        approved    = 0
        in_progress = 0
        paid_count  = 0
        paid_revenue = 0.0

        for j in jobs:
            status_raw  = (j.Job_status or "").strip()
            status_norm = status_raw.upper()

            if status_raw in PROPOSALS_STATUSES:
                proposals += 1

            if status_raw and status_raw not in EXCLUDE_FROM_APPROVED:
                approved += 1

            if status_raw in INPROGRESS_STATUSES:
                in_progress += 1

            if status_norm == "PAID":
                paid_count  += 1
                paid_revenue += j.Gqm_final_prem_in_money or 0.0

        return jsonify({
            "proposals":      proposals,
            "approved_jobs":  approved,
            "in_progress_jobs": in_progress,
            "paid_jobs":      paid_count,
            "paid_revenue":   round(paid_revenue, 2),
            "filter": {"month": month, "year": year},
        }), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un cliente
@client_bp.post("/")
@require_permission("client:create")
@handle_exceptions()
@audit("Client created", entity_type="Client", id_from="response")
def create_client():

    data = request.get_json()
    create_client = ClientCreate.model_validate(data)
    obj = Client(
        **create_client.model_dump(exclude_unset=False, exclude_none=False))

    # 🔘 Función de sincronización
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Client, "ID_Client", "CLI")
        obj.ID_Client = new_id

        # ----------- 🟢 CREAR EN PODIO (SI APLICA)
        if sync_podio:

            podio_fields = map_client_to_podio(obj, session=session)
            podio_service = podio_clients_router.get_service()
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
            "✅ Client creado | client_id=%s | podio_item_id=%s",
            obj.ID_Client,
            obj.podio_item_id
        )

        return obj.model_dump(), 201


# Ruta para actualizar un cliente
@client_bp.patch("/<id_client>")
@require_permission("client:update")
@handle_exceptions()
@audit("Client updated", entity_type="Client", id_param="id_client")
def update_client(id_client):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    data = request.get_json()

    with get_session() as session:
        obj = session.exec(
            select(Client).where(Client.ID_Client == id_client)
        ).first()
        if not obj:
            raise AppException("Client no encontrado.",
                               "client_not_found", 404)

        update_client = ClientUpdate.model_validate(data)
        update_data_dict = update_client.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        logger.info("🔄 Client actualizado | client_id=%s", id_client)

        # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:
            podio_service = podio_clients_router.get_service()
            podio_fields = map_client_to_podio(obj, session=session)

            try:
                podio_service.update_item(
                    int(obj.podio_item_id), podio_fields)

                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🔄 Client actualizado en Podio | client_id=%s | podio_item_id=%s",
                    id_client,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error actualizando Client en Podio | client_id=%s | podio_item_id=%s",
                    id_client,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al actualizar el Client en Podio.",
                    "podio_update_failed",
                    502
                )

        return obj.model_dump(), 200


# Ruta para eliminar un cliente
@client_bp.delete("/<id_client>")
@require_permission("client:delete")
@handle_exceptions()
@audit("Client deleted", entity_type="Client", id_param="id_client")
def delete_client(id_client):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:
        obj = session.exec(select(Client).where(
            Client.ID_Client == id_client)).first()
        if not obj:
            raise AppException("Client no encontrado.",
                               "client_not_found", 404)

        # ----------- 🟢 BORRAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:

            podio_service = podio_clients_router.get_service()

            try:
                podio_service.delete_item(int(obj.podio_item_id))
                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🗑️ Client eliminado en Podio | client_id=%s | podio_item_id=%s",
                    id_client,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error eliminando Client en Podio | client_id=%s | podio_item_id=%s",
                    id_client,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al eliminar el Client en Podio.",
                    "podio_delete_failed",
                    502
                )

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ Client eliminado | client_id=%s",
            id_client
        )

        return jsonify({
            "message": f"Client {id_client} eliminado correctamente"
        }), 200
