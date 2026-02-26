# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ManagerModel import Manager, ManagerCreate, ManagerUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..models.ClientModel import Client
from ..models.link_models.ClientLinks import ClientManagerLink
from src.podio.services.client_services import podio_clients_router
from src.utils.mappers.mapper_aux_functions import register_event

# Blueprint de Manager:
manager_bp = Blueprint(
    "manager_blueprint", __name__, url_prefix="/manager")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los managers
@manager_bp.get("/")
@paginate()
def list_managers():
    try:
        with get_session() as session:
            # Trae todos los managers con info anidada
            statement = (
                select(Manager)
                .options(
                    joinedload(Manager.parent_mgmt_co),
                    joinedload(Manager.client)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            managers_data = [
                add_relationships(manager, ["parent_mgmt_co", "client"])
                for manager in results
            ]

            return managers_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar managers: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar managers: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un managers por ID
@manager_bp.get("/<manager_id>")
def get_manager(manager_id):
    try:
        with get_session() as session:
            statement = (
                select(Manager)
                .options(
                    joinedload(Manager.parent_mgmt_co),
                    joinedload(Manager.client)
                )
                .where(Manager.ID_Manager == manager_id)
            )

            results = session.exec(statement).unique().first()

            if not results:
                return jsonify({"error": "Manager not found"}), 404

            managers_data = add_relationships(
                results, ["parent_mgmt_co", "client"])

            return jsonify(managers_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar manager {manager_id}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar managers: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un manager
@manager_bp.post("/")
def create_manager():
    try:
        data = request.get_json()
        create_manager = ManagerCreate.model_validate(data)
        obj = Manager.model_validate(create_manager)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Manager, "ID_Manager", "MNG")
            obj.ID_Manager = new_id

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un manager con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear manager: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de manager: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un manager
@manager_bp.patch("/<manager_id>")
def update_manager(manager_id):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        sync_podio = request.args.get("sync_podio", "false").lower() == "true"
        with get_session() as session:
            obj = session.get(Manager, manager_id)
            if not obj:
                return jsonify({"error": "Manager not found"}), 404

            update_manager = ManagerUpdate.model_validate(data)
            update_data_dict = update_manager.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            session.add(obj)
            session.commit()
            session.refresh(obj)

            # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
            if sync_podio and "Manager_name" in update_data_dict:

                # 🔎 Buscar todos los links de este manager
                links = session.exec(
                    select(ClientManagerLink)
                    .where(ClientManagerLink.manager_id == manager_id)
                ).all()

                podio_service = podio_clients_router.get_service()

                for link in links:

                    client = session.get(Client, link.clients_id)

                    if not client or not client.podio_item_id:
                        continue

                    if link.rol == "Prop. Manager":
                        field_name = "contact-name"
                    elif link.rol == "Regional Manager":
                        field_name = "regional-manager"
                    else:
                        continue

                    podio_service.update_item(
                        int(client.podio_item_id),
                        {
                            field_name: obj.Manager_name
                        }
                    )

                    register_event(client.podio_item_id)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de manager inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un manager con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar manager: {db_error}")
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
        print(f"Error inesperado al actualizar manager: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un manager
@manager_bp.delete("/<manager_id>")
def delete_manager(manager_id):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Manager, manager_id)
            if not obj:
                return jsonify({"error": "Manager not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Manager {manager_id}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el manager porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al eliminar manager: {db_error}")
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
        print(f"Error inesperado al eliminar manager: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
