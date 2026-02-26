from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.SubcontractorModel import Subcontractor, SubcontractorCreate, SubcontractorUpdate
from ..models.TechnicianModel import Technician
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, load_only
from sqlalchemy import func
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.subcontractor_services import podio_subc_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.subcontractor_mapper import map_subc_to_podio
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger


# Blueprint de Subcontractor
subcontractor_bp = Blueprint(
    "subcontractor_blueprint", __name__, url_prefix="/subcontractors")


# -------------------RUTAS CRUD-------------------#

# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los subcontratistas
@subcontractor_bp.get("/")
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
def list_subcontractors_table():
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 10))
        if page < 1:
            page = 1
        if limit < 1:
            limit = 10
        limit = min(limit, 200)

        status = request.args.get("status")  # filtro opcional por Status

        with get_session() as session:
            # Query ligera solicitando solo las columnas necesarias
            statement = (
                select(Subcontractor)
                .options(
                    load_only(
                        Subcontractor.ID_Subcontractor,
                        Subcontractor.Name,
                        Subcontractor.Organization,
                        Subcontractor.Status,
                        Subcontractor.Email_Address,
                        Subcontractor.Score,
                    )
                )
            )

            # aplicar filtro si viene status
            if status:
                statement = statement.where(Subcontractor.Status == status)

            # total
            count_stmt = select(func.count()).select_from(Subcontractor)
            if status:
                count_stmt = count_stmt.where(Subcontractor.Status == status)
            total = session.exec(count_stmt).one()

            # paginación SQL
            offset = (page - 1) * limit
            statement = statement.order_by(
                Subcontractor.ID_Subcontractor.desc()).offset(offset).limit(limit)

            results = session.exec(statement).unique().all()

            if not results:
                return jsonify({
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "results": []
                }), 200

            out = []
            for s in results:
                out.append({
                    "ID_Subcontractor": s.ID_Subcontractor,
                    "Name": s.Name,
                    "Organization": s.Organization,
                    "Status": s.Status,
                    "Email_Address": s.Email_Address,
                    "Score": s.Score,
                })

            return jsonify({
                "page": page,
                "limit": limit,
                "total": total,
                "results": out
            }), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al listar subcontractors table: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar subcontractors table: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un subcontratista por ID
@subcontractor_bp.get("/<id_subcontractor>")
@handle_exceptions()
def get_subcontractor(id_subcontractor):

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
            .where(Subcontractor.ID_Subcontractor == id_subcontractor)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Subcontractor no encontrado.",
                               "subc_not_found", 404)

        subcontr_data = add_relationships(
            obj, ["technicians.tasks", "orders", "jobs", "attachments",
                  "role", "tlactivity", "skills", "opportunities"])

        return subcontr_data, 200


# Ruta para conseguir un subcontratista por estado
@subcontractor_bp.get("/status/<status>")
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
            return [], 404

        subcontr_data = [
            add_relationships(
                subcontr, ["technicians.tasks", "orders", "jobs", "attachments"])
            for subcontr in results
        ]

        return subcontr_data, 200


# Ruta para conseguir un subcontratista por GQM best service training
@subcontractor_bp.get("/bts/<bts>")
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
@handle_exceptions()
def create_subcontractor():

    data = request.get_json()
    create_subcontractor = SubcontractorCreate.model_validate(data)
    obj = Subcontractor(
        **create_subcontractor.model_dump(exclude_unset=False, exclude_none=False))

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

        return obj.model_dump(), 201


# Ruta para actualizar un subcontratista
@subcontractor_bp.patch("/<subc_id>")
@handle_exceptions()
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

        return obj.model_dump(), 200


# Ruta para eliminar un subcontratista
@subcontractor_bp.delete("/<subc_id>")
@handle_exceptions()
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
