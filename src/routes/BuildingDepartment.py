# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.BldgDeptModel import BuildingDept, BuildingDeptCreate, BuildingDeptUpdate
from ..utils.pagination import paginate
from ..utils.id_generator import generate_custom_id
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.mappers.mapper_aux_functions import register_event
from ..podio.services.bldg_dept_services import podio_bldg_dept_router
from ..utils.mappers.to_podio.bldg_dept_mapper import map_bldg_dept_to_podio
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger


# Blueprint de Building Department:
bldg_dept_bp = Blueprint(
    "bldg_dept_blueprint", __name__, url_prefix="/bldg_dept")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los Building Departments
@bldg_dept_bp.get("/")
@handle_exceptions()
@paginate()
def list_bldg_dept():

    with get_session() as session:
        # Trae todas los Building Departments con info anidada
        statement = (
            select(BuildingDept)
            .options(
                joinedload(BuildingDept.jobs),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        bldg_dept_data = [
            add_relationships(bldg_dept, ["jobs"])
            for bldg_dept in results
        ]

        return bldg_dept_data, 200


# Ruta para conseguir un Building Department por ID
@bldg_dept_bp.get("/<bldg_dept_id>")
@handle_exceptions()
def get_bldg_dept(bldg_dept_id):

    with get_session() as session:
        statement = (
            select(BuildingDept)
            .options(
                joinedload(BuildingDept.jobs)
            )
            .where(BuildingDept.ID_BldgDept == bldg_dept_id)
        )

        results = session.exec(statement).unique().first()

        if not results:
            raise AppException("Building Department not found.",
                               "bldg_dept_not_found", 404)

        bldg_dept_data = add_relationships(
            results, ["jobs"])

        return jsonify(bldg_dept_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un Building Department
@bldg_dept_bp.post("/")
@handle_exceptions()
def create_bldg_dept():

    data = request.get_json()
    create_bldg_dept = BuildingDeptCreate.model_validate(data)
    obj = BuildingDept(
        **create_bldg_dept.model_dump(exclude_unset=False, exclude_none=False))

    # 🔘 Función de sincronización
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:

        # ----------- 🟢 CREAR EN PODIO (SI APLICA)
        if sync_podio:

            podio_fields = map_bldg_dept_to_podio(obj, session)
            podio_service = podio_bldg_dept_router.get_service()
            podio_response = podio_service.create_item(podio_fields)

            # Guardar el podio_item_id en PostgreSQL
            if not podio_response or not podio_response.get("item_id"):
                raise AppException(
                    "No se pudo crear el item en Podio.", "podio_creation_failed", 502)

            # Guardar el podio_item_id en PostgreSQL
            obj.podio_item_id = podio_response["item_id"]

            # Buscar y guardar el ID_BldgDept
            item = podio_service.get_item(obj.podio_item_id)
            formatted_id = item.get("app_item_id_formatted")

            if not formatted_id:
                raise AppException(
                    "No se pudo obtener el ID formateado desde Podio.", "podio_formatted_id_missing", 502)

            obj.ID_BldgDept = formatted_id

            # Anti-loop: registrar evento
            register_event(obj.podio_item_id)

        else:
            # ----------- 🔵 CREAR EN DB
            new_id = generate_custom_id(
                session, BuildingDept, "ID_BldgDept", "BLGDEP")
            obj.ID_BldgDept = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Building Department creado | bldg_dept_id=%s | podio_item_id=%s",
            obj.ID_BldgDept,
            obj.podio_item_id
        )

        return obj.model_dump(), 201


# Ruta para actualizar un Building Department
@bldg_dept_bp.patch("/<bldg_dept_id>")
@handle_exceptions()
def update_bldg_dept(bldg_dept_id):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    data = request.get_json()

    with get_session() as session:
        obj = session.exec(
            select(BuildingDept).where(
                BuildingDept.ID_BldgDept == bldg_dept_id)
        ).first()
        if not obj:
            raise AppException("Building Department not found.",
                               "bldg_dept_not_found", 404)

        update_bldg_dept = BuildingDeptUpdate.model_validate(data)
        update_data_dict = update_bldg_dept.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        logger.info(
            "🔄 Building Department actualizado | bldg_dept_id=%s", bldg_dept_id)

        # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:
            podio_service = podio_bldg_dept_router.get_service()
            podio_fields = map_bldg_dept_to_podio(obj)

            try:
                podio_service.update_item(int(obj.podio_item_id), podio_fields)

                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🔄 Building Department actualizado en Podio | bldg_dept_id=%s | podio_item_id=%s",
                    bldg_dept_id,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error actualizando Building Department en Podio | bldg_dept_id=%s | podio_item_id=%s",
                    bldg_dept_id,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al actualizar el Building Department en Podio.",
                    "podio_update_failed",
                    502
                )

        return obj.model_dump(), 200


# Ruta para eliminar un Building Department
@bldg_dept_bp.delete("/<bldg_dept_id>")
@handle_exceptions()
def delete_bldg_co(bldg_dept_id):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:
        obj = session.exec(select(BuildingDept).where(
            BuildingDept.ID_BldgDept == bldg_dept_id)).first()
        if not obj:
            raise AppException("Building Department not found.",
                               "bldg_dept_not_found", 404)

        # ----------- 🟢 BORRAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_item_id:

            podio_service = podio_bldg_dept_router.get_service()

            try:
                podio_service.delete_item(int(obj.podio_item_id))
                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

                logger.info(
                    "🗑️ Building Department eliminado en Podio | bldg_dept_id=%s | podio_item_id=%s",
                    bldg_dept_id,
                    obj.podio_item_id
                )

            except Exception:
                logger.exception(
                    "❌ Error eliminando Building Department en Podio | bldg_dept_id=%s | podio_item_id=%s",
                    bldg_dept_id,
                    obj.podio_item_id
                )
                raise AppException(
                    "Error al eliminar el Building Department en Podio.",
                    "podio_delete_failed",
                    502
                )

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ Building Department eliminado | bldg_dept_id=%s",
            bldg_dept_id
        )

        return jsonify({
            "message": f"Building Department {bldg_dept_id} eliminado correctamente"
        }), 200
