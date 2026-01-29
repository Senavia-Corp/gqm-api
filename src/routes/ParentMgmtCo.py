# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ParentMgmtCoModel import ParentMgmtCo, PaMgmtCoCreate, PaMgmtCoUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.pa_mgmt_co_services import podio_pa_mgmt_co_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.pa_mgmt_co_mapper import map_parent_to_podio


# Blueprint de Parent Mgmt Co:
parent_mgmt_co_bp = Blueprint(
    "parent_mgmt_co_blueprint", __name__, url_prefix="/parent_mgmt_co")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos las parent mgmt communities
@parent_mgmt_co_bp.get("/")
@paginate()
def list_parent_co():
    try:
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
                return [], 404

            pro_mgmt_co_data = [
                add_relationships(manager, ["managers", "clients"])
                for manager in results
            ]

            return pro_mgmt_co_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar las parent mgmt communities: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(
            f"Error inesperado al listar las parent mgmt communities: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un parent mgmt co por ID
@parent_mgmt_co_bp.get("/<pa_mgmt_co_id>")
def get_manager_co(pa_mgmt_co_id):
    try:
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
                return jsonify({"error": "Parent Mgmt Co not found"}), 404

            pa_mgmt_co_data = add_relationships(
                results, ["managers", "clients"])

            return jsonify(pa_mgmt_co_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar parent mgmt co.: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(
            f"Error inesperado al listar las parent mgmt communities: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un parent mgmt co
@parent_mgmt_co_bp.post("/")
def create_parent_co():
    try:
        data = request.get_json()
        create_parent_co = PaMgmtCoCreate.model_validate(data)
        obj = ParentMgmtCo(
            **create_parent_co.model_dump(exclude_unset=False, exclude_none=False))

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:

            # Mapear a Podio
            podio_fields = map_parent_to_podio(obj, session)
            podio_service = podio_pa_mgmt_co_router.get_service()

            try:
                podio_response = podio_service.create_item(podio_fields)

                # Guardar el podio_item_id en PostgreSQL
                if podio_response and podio_response.get("item_id"):
                    obj.podio_item_id = podio_response["item_id"]

                    # Buscar y guardar el ID_Community_Tracking
                    item = podio_service.get_item(obj.podio_item_id)
                    formatted_id = item.get("app_item_id_formatted")
                    if formatted_id:
                        obj.ID_Community_Tracking = formatted_id
                    else:
                        raise ValueError(
                            "No se pudo obtener app_item_id_formatted de Podio")

                    # Anti-loop: registrar evento
                    register_event(obj.podio_item_id)

                    save_with_retry(session, obj)

                else:
                    print("⚠️ No se pudo obtener los datos de Podio.")

            except Exception as podio_error:
                print(f"⚠️ Error al crear item en Podio: {podio_error}")

            return jsonify(obj.model_dump()), 201

    except ValidationError as e:
        # Error en otros campos o JSON.
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un parent mgmt co con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(
            f"Error de base de datos al crear parent mgmt co: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(
            f"Error inesperado durante la creación de parent mgmt co: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un parent mgmt co
@parent_mgmt_co_bp.patch("/<podio_item_id>")
def update_parent_co(podio_item_id):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.exec(
                select(ParentMgmtCo).where(
                    ParentMgmtCo.podio_item_id == podio_item_id)
            ).first()
            if not obj:
                return jsonify({"error": "ParentMgmtCo not found"}), 404

            update_parent_co = PaMgmtCoUpdate.model_validate(data)
            update_data_dict = update_parent_co.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            # Mapear a Podio
            podio_service = podio_pa_mgmt_co_router.get_service()
            podio_fields = map_parent_to_podio(obj)

            try:
                if obj.podio_item_id:
                    podio_service.update_item(
                        int(obj.podio_item_id), podio_fields)

                    # Anti-loop: registrar evento
                    register_event(obj.podio_item_id)

                    print(
                        f"🧩 ParentMgmtCo {podio_item_id} actualizado en Podio (item_id={obj.podio_item_id})")
                else:
                    # Si no tiene podio_item_id, crearlo en Podio
                    podio_response = podio_service.create_item(podio_fields)
                    if podio_response and podio_response.get("item_id"):
                        obj.podio_item_id = podio_response["item_id"]

                        save_with_retry(session, obj)
                        print(
                            f"✅ ParentMgmtCo {podio_item_id} creado en Podio (item_id={obj.podio_item_id})")

            except Exception as podio_error:
                print(
                    f"⚠️ Error al actualizar/crear ParentMgmtCo en Podio: {podio_error}")

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de parent mgmt co inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe una parent mgmt co con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar parent mgmt co: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al actualizar parent mgmt co: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un parent manager co
@parent_mgmt_co_bp.delete("/<podio_item_id>")
def delete_parent_co(podio_item_id):
    session = None
    try:
        with get_session() as session:
            obj = session.exec(
                select(ParentMgmtCo).where(
                    ParentMgmtCo.podio_item_id == podio_item_id)
            ).first()
            if not obj:
                return jsonify({"error": "ParentMgmtCo not found"}), 404

            # Eliminar en Podio
            podio_service = podio_pa_mgmt_co_router.get_service()
            try:
                podio_service.delete_item(obj.podio_item_id)
                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)
                print(
                    f"🗑️ ParentMgmtCo eliminado en Podio: {obj.podio_item_id}")
            except Exception as podio_error:
                print(
                    f"⚠️ Error borrando ParentMgmtCo en Podio: {podio_error}")

            # Eliminar en DB
            delete_with_retry(session, obj)

            return jsonify({"message": f"ParentMgmtCo {podio_item_id} eliminado correctamente"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar la parent mgmt co porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al eliminar parent mgmt co: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al eliminar parent mgmt co: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
