# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ParentMgmtCoModel import ParentMgmtCo, PaMgmtCoCreate, PaMgmtCoUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..podio.services.pa_mgmt_co_services import podio_pa_mgmt_co_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.pa_mgmt_co_mapper import map_parent_to_podio
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.audit import audit
from src.utils.middleware.auth.routes_protection import require_permission


# Blueprint de Parent Mgmt Co:
parent_mgmt_co_bp = Blueprint(
    "parent_mgmt_co_blueprint", __name__, url_prefix="/parent_mgmt_co")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos las parent mgmt communities
@parent_mgmt_co_bp.get("/")
@require_permission("parent_mgmt_co:read")
@handle_exceptions()
@paginate()
def list_parent_co():

    with get_session() as session:
        # Trae todas las parent mgmt communities con info anidada
        statement = (
            select(ParentMgmtCo)
            .options(
                joinedload(ParentMgmtCo.managers),
                joinedload(ParentMgmtCo.clients)
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        pro_mgmt_co_data = [
            add_relationships(pamgmt, ["managers", "clients"])
            for pamgmt in results]

        return pro_mgmt_co_data, 200


# Ruta para conseguir un parent mgmt co por ID
@parent_mgmt_co_bp.get("/<pa_mgmt_co_id>")
@require_permission("parent_mgmt_co:read")
@handle_exceptions()
def get_manager_co(pa_mgmt_co_id):

    with get_session() as session:
        statement = (
            select(ParentMgmtCo)
            .options(
                joinedload(ParentMgmtCo.managers),
                joinedload(ParentMgmtCo.clients)
            )
            .where(ParentMgmtCo.ID_Community_Tracking == pa_mgmt_co_id)
        )

        results = session.exec(statement).unique().first()

        if not results:
            raise AppException("Parent Mgmt Co not found.",
                               "pmc_not_found", 404)

        pa_mgmt_co_data = add_relationships(
            results, ["managers", "clients"])

        return pa_mgmt_co_data, 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un parent mgmt co
@parent_mgmt_co_bp.post("/")
@require_permission("parent_mgmt_co:create")
@handle_exceptions()
@audit("ParentMgmtCo created", entity_type="ParentMgmtCo", id_from="response")
def create_parent_co():

    data = request.get_json()
    create_parent_co = PaMgmtCoCreate.model_validate(data)
    obj = ParentMgmtCo(
        **create_parent_co.model_dump(exclude_unset=False, exclude_none=False))

    # 🔘 Función de sincronización
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:

        # ----------- 🟢 CREAR EN PODIO (SI APLICA)
        if sync_podio:

            podio_fields = map_parent_to_podio(obj, session)
            podio_service = podio_pa_mgmt_co_router.get_service()
            podio_response = podio_service.create_item(podio_fields)

            # Guardar el podio_item_id en PostgreSQL
            if not podio_response or not podio_response.get("item_id"):
                raise AppException(
                    "No se pudo crear el item en Podio.", "podio_creation_failed", 502)

            # Guardar el podio_item_id en PostgreSQL
            obj.podio_item_id = podio_response["item_id"]

            # Buscar y guardar el ID_Community_Tracking
            item = podio_service.get_item(obj.podio_item_id)
            formatted_id = item.get("app_item_id_formatted")

            if not formatted_id:
                raise AppException(
                    "No se pudo obtener el ID formateado desde Podio.", "podio_formatted_id_missing", 502)

            obj.ID_Community_Tracking = formatted_id

            # Anti-loop: registrar evento
            register_event(obj.podio_item_id)

        else:
            # ----------- 🔵 CREAR EN DB
            new_id = generate_custom_id(
                session, ParentMgmtCo, "ID_Community_Tracking", "PMC")
            obj.ID_Community_Tracking = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ ParentMgmtCo creado | pa_mgmt_co_id=%s | podio_item_id=%s",
            obj.ID_Community_Tracking,
            obj.podio_item_id
        )

        return obj.model_dump(), 201


# Ruta para actualizar un parent mgmt co
@parent_mgmt_co_bp.patch("/<pa_mgmt_co_id>")
@require_permission("parent_mgmt_co:update")
@handle_exceptions()
@audit("ParentMgmtCo updated", entity_type="ParentMgmtCo", id_param="pa_mgmt_co_id")
def update_parent_co(pa_mgmt_co_id):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    data = request.get_json()

    with get_session() as session:
        obj = session.exec(
            select(ParentMgmtCo).where(
                ParentMgmtCo.ID_Community_Tracking == pa_mgmt_co_id)
        ).first()
        if not obj:
            raise AppException("Parent Mgmt Co not found.",
                               "pmc_not_found", 404)

        update_parent_co = PaMgmtCoUpdate.model_validate(data)
        update_data_dict = update_parent_co.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        logger.info(
            "🔄 ParentMgmtCo actualizado | pa_mgmt_co_id=%s", pa_mgmt_co_id)

        # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:
            podio_service = podio_pa_mgmt_co_router.get_service()
            podio_fields = map_parent_to_podio(obj)

            try:
                podio_service.update_item(int(obj.podio_item_id), podio_fields)

                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🔄 ParentMgmtCo actualizado en Podio | pa_mgmt_co_id=%s | podio_item_id=%s",
                    pa_mgmt_co_id,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error actualizando ParentMgmtCo en Podio | pa_mgmt_co_id=%s | podio_item_id=%s",
                    pa_mgmt_co_id,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al actualizar el ParentMgmtCo en Podio.",
                    "podio_update_failed",
                    502
                )

        return obj.model_dump(), 200


# Ruta para eliminar un parent manager co
@parent_mgmt_co_bp.delete("/<pa_mgmt_co_id>")
@require_permission("parent_mgmt_co:delete")
@handle_exceptions()
@audit("ParentMgmtCo deleted", entity_type="ParentMgmtCo", id_param="pa_mgmt_co_id")
def delete_parent_co(pa_mgmt_co_id):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:
        obj = session.exec(select(ParentMgmtCo).where(
            ParentMgmtCo.ID_Community_Tracking == pa_mgmt_co_id)).first()
        if not obj:
            raise AppException("Parent Mgmt Co not found.",
                               "pmc_not_found", 404)

        # ----------- 🟢 BORRAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:

            podio_service = podio_pa_mgmt_co_router.get_service()

            try:
                podio_service.delete_item(int(obj.podio_item_id))
                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🗑️ ParentMgmtCo eliminado en Podio | pa_mgmt_co_id=%s | podio_item_id=%s",
                    pa_mgmt_co_id,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error eliminando ParentMgmtCo en Podio | pa_mgmt_co_id=%s | podio_item_id=%s",
                    pa_mgmt_co_id,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al eliminar el ParentMgmtCo en Podio.",
                    "podio_delete_failed",
                    502
                )

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ ParentMgmtCo eliminado | pa_mgmt_co_id=%s",
            pa_mgmt_co_id
        )

        return jsonify({
            "message": f"ParentMgmtCo {pa_mgmt_co_id} eliminado correctamente"
        }), 200
