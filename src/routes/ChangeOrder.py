# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
import json
from ..database.db_sqlmodel import get_session
from ..models.ChangeOrderModel import ChangeOrder, ChangeOrCreate, ChangeOrUpdate
from ..models.JobModel import Job
from ..models.OrderModel import Order
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from src.utils.id_generator import generate_custom_id
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..podio.services.job_services import podio_jobs_router
from ..utils.mappers.to_podio.order_changeorder_mappers import (
    normalize_podio_fields,
    map_chorder_create_to_podio,
    map_chorder_patch_to_podio,
    map_chorder_delete_to_podio
)
from ..utils.mappers.mapper_aux_functions import register_event


# Blueprint de Change Orders:
change_order_bp = Blueprint(
    "change_order_blueprint", __name__, url_prefix="/change_order")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos las Change Orders
@change_order_bp.get("/")
@handle_exceptions()
@paginate()  # decorador de paginación
def list_change_orders():

    with get_session() as session:

        statement = (
            select(ChangeOrder)
            .options(
                joinedload(ChangeOrder.job)
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200   # El decorador se encarga del formato final

        change_data = [
            # se agrega la relacion FK
            add_relationships(
                changeOr, ["job"])
            for changeOr in results
        ]

        return change_data, 200


# Ruta para conseguir un change order por ID
@change_order_bp.get("/<id_change_order>")
@handle_exceptions()
def get_changeOr_by_id(id_change_order):

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
            raise AppException("Change Order no encontrado.",
                               "ch_order_not_found", 404)

        changeOr_data = add_relationships(
            obj,  ["job"])

        return changeOr_data, 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un change order
@change_order_bp.post("/")
@handle_exceptions()
def create_changeOr():

    data = request.get_json()
    create_changeOr = ChangeOrCreate.model_validate(data)
    obj = ChangeOrder(
        **create_changeOr.model_dump(exclude_unset=False, exclude_none=False))

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
            session, ChangeOrder, "ID_ChangeOrder", "ChO")
        obj.ID_ChangeOrder = new_id

        # ----------- 🟢 SINCRONIZAR EN PODIO (SI APLICA)
        if sync_podio:

            # 1️⃣ Buscar Job
            job = session.exec(
                select(Job).where(Job.podio_item_id == obj.job_podio_id)
            ).first()

            if not job:
                raise AppException("Job no encontrado", "job_not_found", 404)

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
            # Cargar la Order si existe
            if obj.ID_Order:
                order = session.get(Order, obj.ID_Order)
                if not order:
                    raise AppException("Order not found",
                                       "order_not_found", 404)
                obj.order = order  # asignar la relación manualmente

            payload = map_chorder_create_to_podio(
                obj,
                job.Job_type,
                podio_job_fields,
                session
            )
            if payload is None:
                logger.info(
                    "⚠️ Job type '%s' no soporta Change Orders en Podio, se omite sincronización",
                    job.Job_type
                )
            elif not payload:
                # El mapper corrió pero no encontró campos disponibles → error real
                raise AppException(
                    "No se encontró un campo disponible en Podio para la Order",
                    "no_available_order_slot",
                    400
                )
            else:
                try:
                    podio_service.update_item(obj.job_podio_id, payload)
                    register_event(obj.job_podio_id)

                except Exception as podio_err:
                    raise AppException(
                        f"No se pudo sincronizar Change Order con Podio: {podio_err}",
                        "podio_sync_failed",
                        400
                    )

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Change Order creado | chorder_id=%s | job_item_id=%s",
            obj.ID_ChangeOrder,
            obj.job_podio_id
        )

        return obj.model_dump(), 201


# Ruta para actualizar un change order
@change_order_bp.patch("/<id_change_order>")
@handle_exceptions()
def update_changeOr(id_change_order):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    data = request.get_json()

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year",
            400)

    with get_session() as session:

        change_order = session.exec(
            select(ChangeOrder).where(
                ChangeOrder.ID_ChangeOrder == id_change_order)
        ).first()

        if not change_order:
            raise AppException("Change Order not found",
                               "chorder_not_found", 404)

        update_changeOr = ChangeOrUpdate.model_validate(data)
        update_data_dict = update_changeOr.model_dump(
            exclude_unset=True)
        update_data_dict.pop("job_podio_id", None)
        update_data_dict.pop("ID_Jobs", None)
        update_data_dict.pop("ID_Order", None)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():
            setattr(change_order, key, value)

        # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
        if sync_podio:

            if not change_order.podio_field:
                logger.info(
                    "⚠️ Change Order '%s' no tiene campo Podio asignado, se omite sincronización",
                    id_change_order
                )

            else:
                if not change_order.job_podio_id:
                    raise AppException(
                        "Change Order no tiene job_podio_id asignado",
                        "missing_job_podio_id",
                        400
                    )

                job = session.exec(
                    select(Job).where(Job.podio_item_id ==
                                      change_order.job_podio_id)
                ).first()

                if not job:
                    raise AppException("Job not found", "job_not_found", 404)

                podio_service = podio_jobs_router.get_service(
                    job_type=job.Job_type,
                    year=year
                )

                payload = map_chorder_patch_to_podio(
                    change_order, job.Job_type, session)

                try:
                    if payload:
                        podio_service.update_item(
                            change_order.job_podio_id, payload)
                        register_event(change_order.job_podio_id)

                except Exception as podio_err:
                    raise AppException(
                        f"No se pudo sincronizar Change Order con Podio: {podio_err}",
                        "podio_sync_failed",
                        400
                    )

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, change_order)

        logger.info("🔄 Change Order actualizado | chorder_id=%s",
                    id_change_order)

        return change_order.model_dump(), 200


# Ruta para eliminar un change order
@change_order_bp.delete("/<id_change_order>")
@handle_exceptions()
def delete_changeOr(id_change_order):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year",
            400
        )

    with get_session() as session:
        change_order = session.exec(
            select(ChangeOrder).where(
                ChangeOrder.ID_ChangeOrder == id_change_order)
        ).first()

        if not change_order:
            raise AppException("Change Order not found",
                               "chorder_not_found", 404)

        # ----------- 🟢 BORRAR EN PODIO (SI APLICA)
        if sync_podio:

            if not change_order.podio_field:
                logger.info(
                    "⚠️ Change Order '%s' no tiene campo Podio asignado, se omite sincronización",
                    id_change_order
                )

            else:
                if not change_order.job_podio_id:
                    raise AppException(
                        "Change Order no tiene job_podio_id asignado",
                        "missing_job_podio_id",
                        400
                    )

                job = session.exec(
                    select(Job).where(Job.podio_item_id ==
                                      change_order.job_podio_id)
                ).first()

                if not job:
                    raise AppException("Job not found", "job_not_found", 404)

                podio_service = podio_jobs_router.get_service(
                    job_type=job.Job_type,
                    year=year
                )

                payload = map_chorder_delete_to_podio(
                    change_order, job.Job_type)

                try:
                    if payload:
                        podio_service.update_item(
                            change_order.job_podio_id, payload)
                        register_event(change_order.job_podio_id)

                except Exception as podio_err:
                    raise AppException(
                        f"No se pudo sincronizar Change Order con Podio: {podio_err}",
                        "podio_sync_failed",
                        400
                    )

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, change_order)

        logger.info(
            "🗑️ Change Order eliminado | chorder_id=%s",
            id_change_order
        )

        return jsonify({
            "message": f"Deleted Change Order {id_change_order}"
        }), 200
