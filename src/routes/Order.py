# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
import json
from ..database.db_sqlmodel import get_session
from ..models.OrderModel import Order, OrderCreate, OrderUpdate
from ..models.JobModel import Job
from ..models.EstimateCostModel import EstimateCost
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..podio.services.job_services import podio_jobs_router
from ..utils.mappers.to_podio.order_changeorder_mappers import (
    normalize_podio_fields,
    map_order_create_to_podio,
    map_order_patch_to_podio,
    map_order_delete_to_podio
)
from ..utils.mappers.mapper_aux_functions import register_event
from sqlalchemy import or_


# Blueprint de Order:
order_bp = Blueprint("order_blueprint", __name__, url_prefix="/order")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todas las orders
@order_bp.get("/")
@handle_exceptions()
@paginate()
def list_orders():
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
            return [], 200

        order_data = [
            add_relationships(
                order, ["estimate_costs", "subcontractor"])
            for order in results
        ]

        return order_data, 200


# Ruta para conseguir una order por ID
@order_bp.get("/<id_order>")
@handle_exceptions()
def get_order(id_order):

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
            raise AppException("Order no encontrado.", "order_not_found", 404)

        order_data = add_relationships(
            obj, ["estimate_costs", "subcontractor"])

        return order_data, 200


# Ruta para conseguir orders por subc y job (CUBRE AMBOS CASOS: PODIO Y ESTIMATE COSTS)
@order_bp.get("/subcontractor/<id_subcontractor>/job/<id_job>")
@handle_exceptions()
@paginate()
def get_orders_by_subc_and_job(id_subcontractor, id_job):

    with get_session() as session:

        # 1) Buscar Job para conocer podio_item_id (si existe)
        job = session.exec(
            select(Job).where(Job.ID_Jobs == id_job)
        ).first()

        if not job:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        # 2) Construir condición combinada
        # - Si el job NO tiene podio_item_id, solo aplica la relación por estimate_costs
        conditions = [
            # relación real por estimate costs (Order <- EstimateCost -> Job)
            Order.estimate_costs.any(EstimateCost.ID_Jobs == id_job)
        ]

        if job.podio_item_id:
            # relación por podio (Order.job_podio_id == Job.podio_item_id)
            conditions.append(Order.job_podio_id == job.podio_item_id)

        statement = (
            select(Order)
            .options(
                joinedload(Order.estimate_costs).joinedload(EstimateCost.job),
                joinedload(Order.subcontractor),
                joinedload(Order.change_orders),
            )
            .where(Order.ID_Subcontractor == id_subcontractor)
            .where(or_(*conditions))
        )

        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        orders_data = [
            add_relationships(
                order,
                ["estimate_costs.job", "subcontractor", "change_orders"]
            )
            for order in results
        ]

        return orders_data, 200


# Ruta para conseguir una order por job
@order_bp.get("/job/<job_podio_id>")
@handle_exceptions()
@paginate()
def get_orders_by_job(job_podio_id):
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
            return [], 200

        orders_data = [
            add_relationships(order, ["estimate_costs", "subcontractor", "change_orders"])
            for order in results
        ]

        return orders_data, 200


# Ruta para conseguir una Order por ID_Jobs
@order_bp.get("/job-id/<id_job>")
@handle_exceptions()
@paginate()
def get_orders_by_job_id(id_job):
    """
    Retorna orders asociadas a un Job por ID_Jobs, usando el vínculo real:
    Order -> EstimateCost (ID_Order) y EstimateCost.ID_Jobs.
    """
    with get_session() as session:
        statement = (
            select(Order)
            .join(Order.estimate_costs)  # requires relationship
            .options(
                joinedload(Order.estimate_costs),
                joinedload(Order.subcontractor),
                joinedload(Order.change_orders),
            )
            .where(EstimateCost.ID_Jobs == id_job)
        )

        results = session.exec(statement).unique().all()
        if not results:
            return [], 200

        orders_data = [
            add_relationships(order, ["estimate_costs", "subcontractor", "change_orders"])
            for order in results
        ]

        return orders_data, 200

# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una order
@order_bp.post("/")
@handle_exceptions()
def create_order():

    data = request.get_json()
    create_order = OrderCreate.model_validate(data)
    obj = Order(
        **create_order.model_dump(exclude_unset=False, exclude_none=False))

    # 🔘 Función de sincronización
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year",
            400)

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Order, "ID_Order", "ORD")
        obj.ID_Order = new_id

        # ----------- 🟢 SINCRONIZAR EN PODIO (SI APLICA)
        if sync_podio:

            # 1️⃣ Buscar Job
            job = session.exec(
                select(Job).where(Job.podio_item_id == obj.job_podio_id)
            ).first()

            if not job:
                raise AppException("Job not found", "job_not_found", 404)

            # 2️⃣ Obtener servicio
            if not job.Job_type:
                raise AppException(
                    "El Job no tiene Job_type definido",
                    "missing_job_type",
                    400)

            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type,
                year=year)

            # 3️⃣ Obtener job actual desde Podio (necesario)
            podio_job = podio_service.get_item(obj.job_podio_id)
            raw_fields = podio_job.get("fields", {})
            podio_job_fields = normalize_podio_fields(raw_fields)

            # 4️⃣ Construir payload
            payload = map_order_create_to_podio(
                obj,
                job.Job_type,
                podio_job_fields,
                session
            )
            if not payload:
                raise AppException(
                    "No se encontró un campo disponible en Podio para la Order",
                    "no_available_order_slot",
                    400
                )

            print("🚀 Payload que se enviará a Podio:")
            print(json.dumps(payload, indent=4))

            try:
                podio_service.update_item(obj.job_podio_id, payload)
                register_event(obj.job_podio_id)

            except Exception as podio_err:
                raise AppException(
                    f"No se pudo sincronizar Order con Podio: {podio_err}",
                    "podio_sync_failed",
                    400
                )

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Order creado | order_id=%s | job_item_id=%s",
            obj.ID_Order,
            obj.job_podio_id
        )

        return obj.model_dump(), 201


# Ruta para actualizar una order
@order_bp.patch("/<id_order>")
@handle_exceptions()
def update_order(id_order):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    data = request.get_json()

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year",
            400)

    with get_session() as session:

        order = session.exec(
            select(Order).where(Order.ID_Order == id_order)
        ).first()

        if not order:
            raise AppException("Order not found", "order_not_found", 404)

        update_order = OrderUpdate.model_validate(data)
        update_data_dict = update_order.model_dump(
            exclude_unset=True)  # Crea dict limpio
        update_data_dict.pop("job_podio_id", None)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():
            setattr(order, key, value)

        # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
        if sync_podio:

            job = session.exec(
                select(Job).where(Job.podio_item_id == order.job_podio_id)
            ).first()

            if not job:
                raise AppException("Job not found", "job_not_found", 404)

            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type,
                year=year
            )

            payload = map_order_patch_to_podio(order, job.Job_type, session)

            try:
                if payload:
                    podio_service.update_item(order.job_podio_id, payload)
                    register_event(order.job_podio_id)

            except Exception as podio_err:
                raise AppException(
                    f"No se pudo sincronizar Order con Podio: {podio_err}",
                    "podio_sync_failed",
                    400
                )

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, order)

        logger.info("🔄 Order actualizado | order_id=%s", id_order)

        return order.model_dump(), 200


# Ruta para eliminar una order
@order_bp.delete("/<id_order>")
@handle_exceptions()
def delete_order(id_order):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year",
            400
        )

    with get_session() as session:

        order = session.exec(
            select(Order).where(Order.ID_Order == id_order)
        ).first()

        if not order:
            raise AppException("Order not found", "order_not_found", 404)

        # ----------- 🟢 BORRAR EN PODIO (SI APLICA)
        if sync_podio:

            if order.change_orders:
                raise AppException(
                    "No se puede eliminar una Order con Change Orders asociados",
                    "order_has_change_orders",
                    400
                )

            job = session.exec(
                select(Job).where(Job.podio_item_id == order.job_podio_id)
            ).first()

            if not job:
                raise AppException("Job not found", "job_not_found", 404)

            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type,
                year=year
            )

            payload = map_order_delete_to_podio(order, job.Job_type)

            try:
                if payload:
                    podio_service.update_item(order.job_podio_id, payload)
                    register_event(order.job_podio_id)

            except Exception as podio_err:
                raise AppException(
                    f"No se pudo sincronizar Order con Podio: {podio_err}",
                    "podio_sync_failed",
                    400
                )

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, order)

        logger.info(
            "🗑️ Order eliminado | order_id=%s",
            id_order
        )

        return jsonify({
            "message": f"Order {id_order} eliminado correctamente"
        }), 200
