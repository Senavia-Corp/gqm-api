# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
import json
from ..database.db_sqlmodel import get_session
from ..models.OrderModel import Order, OrderCreate, OrderUpdate
from ..models.JobModel import Job
from ..models.EstimateCostModel import EstimateCost
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.job_services import podio_jobs_router
from ..utils.mappers.to_podio.order_mapper import map_order_to_podio, map_order_patch_to_podio, map_order_delete_to_podio
from ..utils.mappers.mapper_aux_functions import register_event


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


# Ruta para conseguir una order por subc y job
@order_bp.get("/subcontractor/<id_subcontractor>/job/<id_job>")
@paginate()
def get_orders_by_subc_and_job(id_subcontractor, id_job):
    try:
        with get_session() as session:

            statement = (
                select(Order)
                .join(Order.subcontractor)
                .join(Order.estimate_costs)
                .join(EstimateCost.job)
                .options(
                    joinedload(Order.estimate_costs).joinedload(
                        EstimateCost.job),
                    joinedload(Order.subcontractor)
                )
                .where(Order.ID_Subcontractor == id_subcontractor)
                .where(EstimateCost.ID_Jobs == id_job)
            )

            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            orders_data = [
                add_relationships(
                    order, ["estimate_costs.job", "subcontractor"])
                for order in results
            ]

            return orders_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Database error while fetching orders: {db_error}")
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

# Ruta para conseguir una order por job
@order_bp.get("/job/<job_podio_id>")
@paginate()
def get_orders_by_job(job_podio_id):
    try:
        # Acepta opcionalmente ?subcontractor=ID o ?id_subcontractor=ID o ?ID_Subcontractor=ID
        subc_id = (
            request.args.get("subcontractor")
            or request.args.get("id_subcontractor")
            or request.args.get("ID_Subcontractor")
        )

        with get_session() as session:
            statement = (
                select(Order)
                .options(
                    joinedload(Order.estimate_costs),
                    joinedload(Order.subcontractor),
                    joinedload(Order.change_orders),
                )
                .where(Order.job_podio_id == job_podio_id)
            )

            if subc_id:
                statement = statement.where(Order.ID_Subcontractor == subc_id)

            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            orders_data = [
                add_relationships(order, ["estimate_costs", "subcontractor", "change_orders"])
                for order in results
            ]

            return orders_data, 200

    except SQLAlchemyError as db_error:
        print(f"Database error while fetching orders for job {job_podio_id}: {db_error}")
        return jsonify({
            "detail": "Internal server error while querying the database.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Unexpected error while fetching orders for job {job_podio_id}: {e}")
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

            # =========== MAPEAR A PODIO
            # 1. Encontrar el Job type para sber que mapeo usar
            job = session.exec(
                select(Job).where(Job.podio_item_id == obj.job_podio_id)
            ).first()

            if not job:
                print("⚠️ Job no encontrado")
                return jsonify(obj.model_dump()), 201

            # 2. Crear payload usando el mapper
            payload = map_order_to_podio(obj, job.Job_type, session)
            save_with_retry(session, obj)

            # 3. Seleccionar service según job type
            podio_service = podio_jobs_router.get_service(job.Job_type)

            # 4. Enviar Formula a Podio
            print("🚀 Payload que se enviará a Podio:")
            print(json.dumps(payload, indent=4))

            try:
                podio_service.update_item(obj.job_podio_id, payload)
                # Anti-loop: registrar evento
                register_event(obj.job_podio_id)
            except Exception as podio_err:
                print(f"❗ Error enviando Order a Podio: {podio_err}")

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

            # =========== MAPEAR A PODIO
            # 1. Crear payload para patch
            payload = map_order_patch_to_podio(obj)

            # 2. Encontrar job type para definir service
            job = session.exec(
                select(Job).where(Job.podio_item_id == obj.job_podio_id)
            ).first()

            if job:
                podio_service = podio_jobs_router.get_service(job.Job_type)
                try:
                    podio_service.update_item(obj.job_podio_id, payload)

                    # Anti-loop: registrar evento
                    register_event(obj.job_podio_id)

                except Exception as podio_err:
                    print("❗ Error enviando PATCH a Podio:", podio_err)

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
            try:
                payload = map_order_delete_to_podio(obj)
                print(payload)

                job = session.exec(
                    select(Job).where(Job.podio_item_id == obj.job_podio_id)
                ).first()

                if job:
                    podio_service = podio_jobs_router.get_service(job.Job_type)
                    podio_service.update_item(obj.job_podio_id, payload)

                    # Anti-loop: registrar evento
                    register_event(obj.job_podio_id)

            except Exception as podio_err:
                print("❗ Error eliminando campo TECH en Podio:", podio_err)

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
