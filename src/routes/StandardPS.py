# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.StandardPSModel import StandardPS, StandardPSCreate, StandardPSUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de StandardPS:
standard_ps_bp = Blueprint("standard_ps_blueprint",
                           __name__, url_prefix="/standard_ps")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los StandardPS
@standard_ps_bp.get("/")
@paginate()
def list_standard_ps():
    try:
        with get_session() as session:

            statement = (
                select(StandardPS)
                .options(
                    joinedload(StandardPS.client),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            purc_data = [
                add_relationships(
                    purc, ["client"])
                for purc in results
            ]

            return purc_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar StandardPS: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar StandardPS: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un StandardPS por ID
@standard_ps_bp.get("/<id_standard_ps>")
def get_standard_ps(id_standard_ps):
    try:
        with get_session() as session:

            statement = (
                select(StandardPS)
                .options(
                    joinedload(StandardPS.client)
                )
                .where(StandardPS.ID_StandardPS == id_standard_ps)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "StandardPS not found"}), 404

            purc_data = add_relationships(
                obj, ["client"])

            return jsonify(purc_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar StandardPS {id_standard_ps}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar StandardPS: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una StandardPS
@standard_ps_bp.post("/")
def create_standard_ps():
    try:
        data = request.get_json()
        create_standard_ps = StandardPSCreate.model_validate(data)
        obj = StandardPS.model_validate(create_standard_ps)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, StandardPS, "ID_StandardPS", "SPS")
            obj.ID_StandardPS = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando viola una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un StandardPS con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear StandardPS: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de StandardPS: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar una StandardPS
@standard_ps_bp.patch("/<id_standard_ps>")
def update_standard_ps(id_standard_ps):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(StandardPS, id_standard_ps)
            if not obj:
                return jsonify({"error": "StandardPS not found"}), 404

            update_standard_ps = StandardPSUpdate.model_validate(data)
            update_data_dict = update_standard_ps.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de StandardPS inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un StandardPS con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar StandardPS: {db_error}")
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
        print(f"Error inesperado al actualizar StandardPS: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar una StandardPS
@standard_ps_bp.delete("/<id_standard_ps>")
def delete_standard_ps(id_standard_ps):
    session = None
    try:
        with get_session() as session:
            obj = session.get(StandardPS, id_standard_ps)
            if not obj:
                return jsonify({"error": "StandardPS not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted StandardPS {id_standard_ps}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un StandardPS que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el StandardPS porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar StandardPS: {db_error}")
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
        print(f"Error inesperado al eliminar StandardPS: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
