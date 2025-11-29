# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.PropertyManagerModel import PropertyManager, PrManagerCreate, PrManagerUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate

# Blueprint de Property Manager:
property_manager_bp = Blueprint(
    "property_manager_blueprint", __name__, url_prefix="/property_manager")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los property managers
@property_manager_bp.get("/")
@paginate()
def list_pr_managers():
    try:
        with get_session() as session:
            # Trae todos los property managers con info anidada
            statement = (
                select(PropertyManager)
                .options(
                    joinedload(PropertyManager.property_mgmt_co),
                    joinedload(PropertyManager.client)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            managers_data = [
                add_relationships(manager, ["property_mgmt_co", "client"])
                for manager in results
            ]

            return managers_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar property managers: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar property managers: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un property managers por ID
@property_manager_bp.get("/<property_manager_id>")
def get_manager(property_manager_id):
    try:
        with get_session() as session:
            statement = (
                select(PropertyManager)
                .options(
                    joinedload(PropertyManager.property_mgmt_co),
                    joinedload(PropertyManager.client)
                )
                .where(PropertyManager.ID_PropertyManager == property_manager_id)
            )

            results = session.exec(statement).unique().first()

            if not results:
                return jsonify({"error": "Property Manager not found"}), 404

            managers_data = add_relationships(
                results, ["property_mgmt_co", "client"])

            return jsonify(managers_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar property manager {property_manager_id}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar property managers: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un property manager
@property_manager_bp.post("/")
def create_manager():
    try:
        data = request.get_json()
        create_manager = PrManagerCreate.model_validate(data)
        obj = PropertyManager.model_validate(create_manager)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, PropertyManager, "ID_PropertyManager", "PrM")
            obj.ID_PropertyManager = new_id

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un property manager con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear property manager: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de property manager: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un property manager
@property_manager_bp.patch("/<property_manager_id>")
def update_manager(property_manager_id):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(PropertyManager, property_manager_id)
            if not obj:
                return jsonify({"error": "Property Manager not found"}), 404

            update_manager = PrManagerUpdate.model_validate(data)
            update_data_dict = update_manager.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de property manager inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un property manager con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar property manager: {db_error}")
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
        print(f"Error inesperado al actualizar property manager: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un property manager
@property_manager_bp.delete("/<property_manager_id>")
def delete_manager(property_manager_id):
    session = None
    try:
        with get_session() as session:
            obj = session.get(PropertyManager, property_manager_id)
            if not obj:
                return jsonify({"error": "Property Manager not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Property Manager {property_manager_id}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el property manager porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al eliminar property manager: {db_error}")
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
        print(f"Error inesperado al eliminar property manager: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
