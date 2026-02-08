# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.PurchaseOrderModel import PurchaseOrder, POrderCreate, POrderUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de PurchaseOrder:
purchase_order_bp = Blueprint("purchase_order_blueprint",
                              __name__, url_prefix="/purchase_order")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los purchase_order
@purchase_order_bp.get("/")
@paginate()
def list_purchase_order():
    try:
        with get_session() as session:

            statement = (
                select(PurchaseOrder)
                .options(
                    joinedload(PurchaseOrder.purchase),
                    joinedload(PurchaseOrder.porder_items),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            fd_data = [
                add_relationships(
                    fd, ["purchase", "porder_items"])
                for fd in results
            ]

            return fd_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar purchase order: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar purchase order: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un purchase order por ID
@purchase_order_bp.get("/<id_purchase_order>")
def get_purchase_order(id_purchase_order):
    try:
        with get_session() as session:

            statement = (
                select(PurchaseOrder)
                .options(
                    joinedload(PurchaseOrder.purchase),
                    joinedload(PurchaseOrder.porder_items),
                )
                .where(PurchaseOrder.ID_PurchaseOrder == id_purchase_order)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "PurchaseOrder not found"}), 404

            fd_data = add_relationships(
                obj, ["purchase", "porder_items"])

            return jsonify(fd_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar purchase order {id_purchase_order}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar purchase order: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un purchase order
@purchase_order_bp.post("/")
def create_purchase_order():
    try:
        data = request.get_json()
        create_purchase_order = POrderCreate.model_validate(data)
        obj = PurchaseOrder.model_validate(create_purchase_order)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, PurchaseOrder, "ID_PurchaseOrder", "PO")
            obj.ID_PurchaseOrder = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando viola una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un purchase order con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear purchase order: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de purchase order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un purchase order
@purchase_order_bp.patch("/<id_purchase_order>")
def update_purchase_order(id_purchase_order):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(PurchaseOrder, id_purchase_order)
            if not obj:
                return jsonify({"error": "PurchaseOrder not found"}), 404

            update_purchase_order = POrderUpdate.model_validate(data)
            update_data_dict = update_purchase_order.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de purchase order inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un purchase order con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar purchase order: {db_error}")
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
        print(f"Error inesperado al actualizar purchase order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un purchase order
@purchase_order_bp.delete("/<id_purchase_order>")
def delete_purchase_order(id_purchase_order):
    session = None
    try:
        with get_session() as session:
            obj = session.get(PurchaseOrder, id_purchase_order)
            if not obj:
                return jsonify({"error": "PurchaseOrder not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted PurchaseOrder {id_purchase_order}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un purchase order que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el purchase order porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar purchase order: {db_error}")
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
        print(f"Error inesperado al eliminar purchase order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
