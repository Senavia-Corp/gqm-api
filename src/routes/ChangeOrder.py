# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ChangeOrderModel import ChangeOrder, ChangeOrCreate, ChangeOrUpdate
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from src.utils.id_generator import generate_custom_id
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de Change Orders:
change_order_bp = Blueprint(
    "change_order_blueprint", __name__, url_prefix="/change_order")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos las Change Orders
@change_order_bp.get("/")
@paginate()  # decorador de paginación
def list_change_orders():
    try:
        with get_session() as session:

            statement = (
                select(ChangeOrder)
                .options(
                    joinedload(ChangeOrder.job)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404   # El decorador se encarga del formato final

            change_data = [
                # se agrega la relacion FK
                add_relationships(
                    changeOr, ["job"])
                for changeOr in results
            ]

            return change_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar change orders: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar change orders: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un change order por ID
@change_order_bp.get("/<id_change_order>")
def get_changeOr_by_id(id_change_order):
    try:
        with get_session() as session:
            statement = (
                select(ChangeOrder)
                .options(
                    joinedload(ChangeOrder.job)
                )
                .where(ChangeOrder.ID_ChangeOrder == id_change_order)
            )
            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Change Order not found"}), 404

            changeOr_data = add_relationships(
                obj,  ["job"])

            return jsonify(changeOr_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar change order {id_change_order}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar change orders: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un change order
@change_order_bp.post("/")
def create_changeOr():
    try:
        data = request.get_json()
        create_changeOr = ChangeOrCreate.model_validate(data)
        obj = ChangeOrder.model_validate(create_changeOr)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, ChangeOrder, "ID_ChangeOrder", "ChO")
            obj.ID_ChangeOrder = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un change order con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear change order: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de change order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un change order
@change_order_bp.patch("/<id_change_order>")
def update_changeOr(id_change_order):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(ChangeOrder, id_change_order)
            if not obj:
                return jsonify({"error": "Change Order not found"}), 404

            update_changeOr = ChangeOrUpdate.model_validate(data)
            update_data_dict = update_changeOr.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de change order inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un change order con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar change order: {db_error}")
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
        print(f"Error inesperado al actualizar change order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un change order
@change_order_bp.delete("/<id_change_order>")
def delete_changeOr(id_change_order):
    session = None
    try:
        with get_session() as session:
            obj = session.get(ChangeOrder, id_change_order)
            if not obj:
                return jsonify({"error": "Change Order not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted Change Order {id_change_order}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un change order que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el change order porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar change order: {db_error}")
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
        print(f"Error inesperado al eliminar change order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
