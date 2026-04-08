# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.MultiplierRModel import MultiplierR, MultiplierRBase
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError

# Blueprint de Member:
multiplier_bp = Blueprint("multiplier_blueprint",
                          __name__, url_prefix="/multiplier")

# -------------------RUTAS CRUD-------------------#

# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los miembros GQM


@multiplier_bp.get("/")
@paginate()  # decorador de paginación
def list_multipliers():
    try:
        with get_session() as session:
            statement = (select(MultiplierR))
            results = session.exec(statement).all()

            if not results:
                return [], 404   # El decorador se encarga del formato final

            multiplier_data = [obj.model_dump() for obj in results]
            return multiplier_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar rango de multiplicadores: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar rango de multiplicadores: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un rango de multiplicadores por ID_MultiplierR
@multiplier_bp.get("/<id_multiplier>")
def get_member_by_id(id_multiplier):
    try:
        with get_session() as session:
            statement = (
                select(MultiplierR)
                # .options(joinedload(Member.client))
                .where(MultiplierR.ID_MultiplierR == id_multiplier)
            )

            obj = session.exec(statement).first()

            if not obj:
                return jsonify({"error": "Multiplier not found"}), 404

            # Construir JSON limpio con la info del multiplicador
            multiplier_data = obj.model_dump()

            return jsonify(multiplier_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar multiplicador {id_multiplier}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar multiplicadores: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un multiplicador
@multiplier_bp.post("/")
def create_multiplier():
    try:
        data = request.get_json()
        create_multiplier = MultiplierRBase.model_validate(data)
        obj = MultiplierR.model_validate(create_multiplier)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, MultiplierR, "ID_MultiplierR", "MULR")
            obj.ID_MultiplierR = new_id

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un multiplicador con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear multiplicador: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de multiplicador: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un multiplicador
@multiplier_bp.patch("/<id_multiplier>")
def update_multiplier(id_multiplier):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(MultiplierR, id_multiplier)
            if not obj:
                return jsonify({"error": "Multiplier not found"}), 404

            update_multiplier = MultiplierRBase.model_validate(data)
            update_data_dict = update_multiplier.model_dump(
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
            "detail": "Error de validación: Datos del multiplicador inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un multiplicador con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar multiplicador: {db_error}")
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
        print(f"Error inesperado al actualizar multiplicador: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un multiplicador
@multiplier_bp.delete("/<id_multiplier>")
def delete_member(id_multiplier):
    session = None
    try:
        with get_session() as session:
            obj = session.get(MultiplierR, id_multiplier)
            if not obj:
                return jsonify({"error": "Multiplier not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Multiplierr {id_multiplier}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un miembro GQM que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el multiplicador porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar multiplicador: {db_error}")
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
        print(f"Error inesperado al eliminar multiplicador: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
