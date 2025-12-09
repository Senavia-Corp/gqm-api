# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.OrderModel import Order, OrderCreate, OrderUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry

from ..podio.services.job_services import podio_jobs_router

from ..utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid
from ..utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from ..utils.mappers.to_podio.par_mapper import map_job_to_podio_par

# Blueprint de Order:
order_bp = Blueprint("order_blueprint", __name__, url_prefix="/order")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todas las orders
@order_bp.get("/")
@paginate()
def list_orders():
    try:
        with get_session() as session:
            statement = (
                select(Order)
                .options(
                    joinedload(Order.estimate_costs),
                    joinedload(Order.subcontractor),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            order_data = [
                add_relationships(
                    order, ["estimate_costs", "subcontractor"])
                for order in results
            ]

            return order_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Database error while listing orders: {db_error}")
        return jsonify({
            "detail": "Internal server error while querying the database.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Unexpected error while listing orders: {e}")
        return jsonify({
            "detail": "Unexpected internal server error.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir una order por ID
@order_bp.get("/<id_order>")
def get_order(id_order):
    try:
        with get_session() as session:
            statement = (
                select(Order)
                .options(
                    joinedload(Order.estimate_costs),
                    joinedload(Order.subcontractor),
                )
                .where(Order.ID_Order == id_order)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Order not found"}), 404

            order_data = add_relationships(
                obj, ["estimate_costs", "subcontractor"])

            return jsonify(order_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Database error while fetching order {id_order}: {db_error}")
        return jsonify({
            "detail": "Internal server error while querying the database.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Unexpected error while listing orders: {e}")
        return jsonify({
            "detail": "Unexpected internal server error.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una order
@order_bp.post("/")
def create_order():
    try:
        data = request.get_json()
        create_order = OrderCreate.model_validate(data)
        obj = Order(
            **create_order.model_dump(exclude_unset=False, exclude_none=False))

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "The request must contain valid JSON."}), 400
        print(f"Unexpected error in data preparation: {e}")
        return jsonify({"detail": "Unexpected server error."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Order, "ID_Order", "ORD")
            obj.ID_Order = new_id

            save_with_retry(session, obj)

            # Mapear a Podio

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "An order with this unique value already exists."
        else:
            detail = "Data integrity error (e.g., missing required data or invalid foreign key)."
        print(f"Data integrity error: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Database error while creating order: {db_error}")
        return jsonify({
            "detail": "Internal server error when interacting with the database.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Unexpected error during order creation: {e}")
        return jsonify({
            "detail": "An unexpected and uncontrolled error occurred on the server.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar una order
@order_bp.patch("/<id_order>")
def update_order(id_order):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Order, id_order)
            if not obj:
                return jsonify({"error": "Order not found"}), 404

            update_order = OrderUpdate.model_validate(data)
            update_data_dict = update_order.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            # Mapear a Podio

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de order inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un order con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar order: {db_error}")
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
        print(f"Error inesperado al actualizar order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar una order
@order_bp.delete("/<id_order>")
def delete_order(id_order):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Order, id_order)
            if not obj:
                return jsonify({"error": "Order not found"}), 404

            # Eliminar en Podio

            # Eliminar en DB
            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted Order {id_order}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar una order que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el order porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar order: {db_error}")
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
        print(f"Error inesperado al eliminar order: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
