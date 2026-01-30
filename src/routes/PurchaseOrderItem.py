# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.PurchaseOrderItemModel import PurchaseOrderItem, POrderItemCreate, POrderItemUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de PurchaseOrderItem:
purchase_order_item_bp = Blueprint("purchase_order_item_blueprint",
                                   __name__, url_prefix="/purchase_order_item")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los purchase order items
@purchase_order_item_bp.get("/")
@paginate()
def list_po_items():
    try:
        with get_session() as session:

            statement = (
                select(PurchaseOrderItem)
                .options(
                    joinedload(PurchaseOrderItem.purchase_order)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            fd_data = [
                add_relationships(
                    fd, ["purchase_order"])
                for fd in results
            ]

            return fd_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar purchase order items: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar purchase order items: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un purchase order item por ID
@purchase_order_item_bp.get("/<id_po_item>")
def get_po_item(id_po_item):
    try:
        with get_session() as session:

            statement = (
                select(PurchaseOrderItem)
                .options(
                    joinedload(PurchaseOrderItem.purchase_order)
                )
                .where(PurchaseOrderItem.ID_PurchaseOrderItem == id_po_item)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "PurchaseOrderItem not found"}), 404

            fd_data = add_relationships(
                obj, ["purchase_order"])

            return jsonify(fd_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar purchase order item {id_po_item}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar purchase order item: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un purchase order item
@purchase_order_item_bp.post("/")
def create_po_item():
    try:
        data = request.get_json()
        create_po_item = POrderItemCreate.model_validate(data)
        obj = PurchaseOrderItem.model_validate(create_po_item)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, PurchaseOrderItem, "ID_PurchaseOrderItem", "POI")
            obj.ID_PurchaseOrderItem = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando viola una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un purchase order item con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(
            f"Error de base de datos al crear purchase order item: {db_error}")
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
            f"Error inesperado durante la creación de purchase order item: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un purchase order item
@purchase_order_item_bp.patch("/<id_po_item>")
def update_po_item(id_po_item):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(PurchaseOrderItem, id_po_item)
            if not obj:
                return jsonify({"error": "PurchaseOrderItem not found"}), 404

            update_po_item = POrderItemUpdate.model_validate(data)
            update_data_dict = update_po_item.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de purchase order item inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un purchase order item con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar purchase order item: {db_error}")
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
        print(f"Error inesperado al actualizar purchase order item: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un purchase order item
@purchase_order_item_bp.delete("/<id_po_item>")
def delete_po_item(id_po_item):
    session = None
    try:
        with get_session() as session:
            obj = session.get(PurchaseOrderItem, id_po_item)
            if not obj:
                return jsonify({"error": "PurchaseOrderItem not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted PurchaseOrderItem {id_po_item}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un purchase order item que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el purchase order item porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al eliminar purchase order item: {db_error}")
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
        print(f"Error inesperado al eliminar purchase order item: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
