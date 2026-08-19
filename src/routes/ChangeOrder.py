# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
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
from src.utils.audit import audit
from src.utils.job_calculator import recalculate_and_apply_from_change_order

# Blueprint de Change Orders:
change_order_bp = Blueprint(
    "change_order_blueprint", __name__, url_prefix="/change_order")


def _sync_order_adj_formula(order_id: str, session) -> None:
    """
    Recalcula y persiste Order.Adj_formula para la Order indicada.
    No hace commit — el llamador es responsable.
    """
    order = session.exec(select(Order).where(
        Order.ID_Order == order_id)).first()
    if not order:
        return

    cos = session.exec(
        select(ChangeOrder).where(ChangeOrder.ID_Order == order_id)
    ).all()

    base_formula = float(order.Formula or 0)
    co_sum = sum(float(co.ChangeOrderFormula or 0) for co in cos)
    new_adj = base_formula + co_sum

    order.Adj_formula = new_adj
    session.add(order)
    logger.info(
        "🔢 Order.Adj_formula actualizado | order_id=%s | base=%.2f | co_sum=%.2f | adj=%.2f",
        order_id, base_formula, co_sum, new_adj
    )


# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#

@change_order_bp.get("/")
@handle_exceptions()
@paginate()
def list_change_orders():
    with get_session() as session:
        statement = (
            select(ChangeOrder)
            .options(joinedload(ChangeOrder.job))
        )
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(co, ["job"]) for co in results], 200


@change_order_bp.get("/<id_change_order>")
@handle_exceptions()
def get_changeOr_by_id(id_change_order):
    with get_session() as session:
        statement = (
            select(ChangeOrder)
            .options(joinedload(ChangeOrder.job))
            .where(ChangeOrder.ID_ChangeOrder == id_change_order)
        )
        obj = session.exec(statement).unique().first()
        if not obj:
            raise AppException("Change Order no encontrado.",
                               "ch_order_not_found", 404)
        return add_relationships(obj, ["job"]), 200


# --------------- RUTAS POST, PATCH AND DELETE ----------#

@change_order_bp.post("/")
@handle_exceptions()
@audit("Change Order created", entity_type="ChangeOrder", id_from="response", job_id_from="body")
def create_changeOr():

    data = request.get_json()
    create_changeOr = ChangeOrCreate.model_validate(data)
    obj = ChangeOrder(
        **create_changeOr.model_dump(exclude_unset=False, exclude_none=False))

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year", 400)

    with get_session() as session:

        # REG-012 (decisión confirmada): PAR usa solo pagos parciales y NO
        # admite Change Orders. Antes esto fallaba en silencio: el mapper
        # devolvía None y el CO se guardaba solo en BD (divergencia BD↔Podio).
        # Ahora se rechaza SIEMPRE (con o sin sync_podio), antes de tocar nada.
        # Resolver el job por CUALQUIERA de sus dos identificadores. Antes solo
        # se buscaba por job_podio_id: si el cliente no lo enviaba (el panel
        # manda `jobPodioId ?? null`), la consulta no encontraba nada, el `and`
        # de abajo cortocircuitaba y la regla PAR no llegaba a evaluarse — el CO
        # se guardaba solo en BD, justo la divergencia que este bloque impide.
        job_for_type = None
        if obj.job_podio_id:
            job_for_type = session.exec(
                select(Job).where(Job.podio_item_id == obj.job_podio_id)
            ).first()
        if job_for_type is None and obj.ID_Jobs:
            job_for_type = session.get(Job, obj.ID_Jobs)

        if job_for_type and job_for_type.Job_type == "PAR":
            raise AppException(
                "Los jobs PAR no admiten Change Orders (usan pagos parciales).",
                "par_change_orders_unsupported", 422)

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, ChangeOrder, "ID_ChangeOrder", "ChO")
        obj.ID_ChangeOrder = new_id

        # ----------- 🟢 SINCRONIZAR EN PODIO (SI APLICA)
        if sync_podio:

            job = job_for_type
            if not job:
                raise AppException("Job no encontrado", "job_not_found", 404)

            if not job.Job_type:
                raise AppException(
                    "El Job no tiene Job_type definido", "missing_job_type", 400)

            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type, year=year)

            podio_job = podio_service.get_item(obj.job_podio_id)
            raw_fields = podio_job.get("fields", {})
            podio_job_fields = normalize_podio_fields(raw_fields)

            if obj.ID_Order:
                order = session.get(Order, obj.ID_Order)
                if not order:
                    raise AppException("Order not found",
                                       "order_not_found", 404)
                obj.order = order

            payload = map_chorder_create_to_podio(
                obj, job.Job_type, podio_job_fields, session)

            if not payload:
                # Con PAR ya rechazado arriba, None solo puede significar
                # "sin slots de CO disponibles" — jamás guardar solo en BD.
                raise AppException(
                    "No se encontró un campo disponible en Podio para el Change Order",
                    "no_available_order_slot", 400
                )
            else:
                try:
                    podio_service.update_item(obj.job_podio_id, payload)
                    register_event(obj.job_podio_id)
                except Exception as podio_err:
                    raise AppException(
                        f"No se pudo sincronizar Change Order con Podio: {podio_err}",
                        "podio_sync_failed", 400
                    )

        # ----------- 💾 GUARDAR CO EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Change Order creado | chorder_id=%s | job_item_id=%s",
            obj.ID_ChangeOrder, obj.job_podio_id
        )

        # REG-142: notificar el nuevo CO al subcontratista de la orden (no bloqueante)
        try:
            from src.models.SubcontractorModel import Subcontractor
            from src.services.email_service import send_new_order_or_co
            if obj.ID_Order:
                _order = session.get(Order, obj.ID_Order)
                if _order and _order.ID_Subcontractor:
                    _sub = session.get(Subcontractor, _order.ID_Subcontractor)
                    if _sub and _sub.Email_Address:
                        send_new_order_or_co(
                            _sub.Email_Address,
                            _sub.Name or _sub.Organization or "Subcontractor",
                            "change order", obj.Name or obj.ID_ChangeOrder,
                            job_for_type.ID_Jobs if job_for_type else None)
        except Exception:
            logger.exception("No se pudo notificar el nuevo change order")

        # ── Si el CO está vinculado a una Order, actualizar su Adj_formula ──
        # Esto debe ocurrir ANTES del recálculo del Job para que el calculador
        # lea el Adj_formula correcto al sumar los Adj_formula de las Orders.
        if obj.ID_Order:
            _sync_order_adj_formula(obj.ID_Order, session)

        # ── Recálculo automático del Job ──────────────────────────────────
        recalculate_and_apply_from_change_order(obj, session)
        session.commit()
        # ─────────────────────────────────────────────────────────────────

        # C3: sin este refresh la respuesta salia con `podio_field: null` aunque
        # el hueco SI quedaba persistido, y el panel no podia decir a que hueco
        # habia ido el change order sin releer.
        session.refresh(obj)
        return obj.model_dump(), 201


@change_order_bp.patch("/<id_change_order>")
@handle_exceptions()
@audit("Change Order updated", entity_type="ChangeOrder", id_param="id_change_order", job_id_from="response")
def update_changeOr(id_change_order):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    data = request.get_json()

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year", 400)

    with get_session() as session:

        change_order = session.exec(
            select(ChangeOrder).where(
                ChangeOrder.ID_ChangeOrder == id_change_order)
        ).first()
        if not change_order:
            raise AppException("Change Order not found",
                               "chorder_not_found", 404)

        # REG-012: mismo guard que el POST — PAR no admite Change Orders
        # (cubre COs legado pre-fix ligados a jobs PAR).
        job_of_co = session.exec(
            select(Job).where(Job.podio_item_id == change_order.job_podio_id)
        ).first()
        if job_of_co and job_of_co.Job_type == "PAR":
            raise AppException(
                "Los jobs PAR no admiten Change Orders (usan pagos parciales).",
                "par_change_orders_unsupported", 422)

        update_changeOr = ChangeOrUpdate.model_validate(data)
        update_data_dict = update_changeOr.model_dump(exclude_unset=True)
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
                        "missing_job_podio_id", 400
                    )

                job = session.exec(
                    select(Job).where(Job.podio_item_id ==
                                      change_order.job_podio_id)
                ).first()
                if not job:
                    raise AppException("Job not found", "job_not_found", 404)

                podio_service = podio_jobs_router.get_service(
                    job_type=job.Job_type, year=year)

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
                        "podio_sync_failed", 400
                    )

        # ----------- 💾 GUARDAR CO EN DB
        save_with_retry(session, change_order)

        logger.info("🔄 Change Order actualizado | chorder_id=%s",
                    id_change_order)

        # ── Si el CO está vinculado a una Order, actualizar su Adj_formula ──
        if change_order.ID_Order:
            _sync_order_adj_formula(change_order.ID_Order, session)

        # ── Recálculo automático del Job ──────────────────────────────────
        recalculate_and_apply_from_change_order(change_order, session)
        session.commit()
        # ─────────────────────────────────────────────────────────────────

        return change_order.model_dump(), 200


@change_order_bp.delete("/<id_change_order>")
@handle_exceptions()
@audit("Change Order deleted", entity_type="ChangeOrder", id_param="id_change_order", job_id_from="body")
def delete_changeOr(id_change_order):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year", 400)

    with get_session() as session:

        change_order = session.exec(
            select(ChangeOrder).where(
                ChangeOrder.ID_ChangeOrder == id_change_order)
        ).first()
        if not change_order:
            raise AppException("Change Order not found",
                               "chorder_not_found", 404)

        # Capturar referencias ANTES de borrar
        order_id_for_sync = change_order.ID_Order   # None si es CO general
        co_snapshot = ChangeOrder(
            ID_ChangeOrder=change_order.ID_ChangeOrder,
            ID_Jobs=change_order.ID_Jobs,
            ID_Order=change_order.ID_Order,
            job_podio_id=change_order.job_podio_id,
        )

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
                        "missing_job_podio_id", 400
                    )

                job = session.exec(
                    select(Job).where(Job.podio_item_id ==
                                      change_order.job_podio_id)
                ).first()
                if not job:
                    raise AppException("Job not found", "job_not_found", 404)

                podio_service = podio_jobs_router.get_service(
                    job_type=job.Job_type, year=year)

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
                        "podio_sync_failed", 400
                    )

        # ----------- 🔴 BORRAR CO EN DB
        delete_with_retry(session, change_order)

        logger.info("🗑️ Change Order eliminado | chorder_id=%s",
                    id_change_order)

        # ── Si el CO estaba vinculado a una Order, actualizar su Adj_formula ─
        # El CO ya fue borrado, así que _sync_order_adj_formula lo excluirá
        # automáticamente al recalcular la suma desde la DB.
        if order_id_for_sync:
            _sync_order_adj_formula(order_id_for_sync, session)

        # ── Recálculo automático del Job ──────────────────────────────────
        recalculate_and_apply_from_change_order(co_snapshot, session)
        session.commit()
        # ─────────────────────────────────────────────────────────────────

        return jsonify({"message": f"Deleted Change Order {id_change_order}"}), 200
