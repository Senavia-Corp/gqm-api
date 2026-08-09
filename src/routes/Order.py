# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
import json
from ..database.db_sqlmodel import get_session
from ..models.OrderModel import Order, OrderCreate, OrderUpdate
from ..models.JobModel import Job
from ..models.EstimateCostModel import EstimateCost
from ..models.FinancialDocModel import FinancialDocument
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
from src.utils.audit import actor_member_id, audit, log_activity, SOURCE_APP
from src.utils.job_calculator import recalculate_and_apply, recalculate_order_formulas  # ← MODIFIED

# Blueprint de Order:
order_bp = Blueprint("order_blueprint", __name__, url_prefix="/order")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
def _scope_orders_statement(statement):
    """Portal: un subcontratista solo ve SUS orders (REG-110)."""
    from src.utils.middleware.auth.routes_protection import portal_scope
    p_role, p_id = portal_scope()
    if p_role == "subcontractor":
        return statement.where(Order.ID_Subcontractor == p_id)
    return statement


@order_bp.get("/")
@handle_exceptions()
@paginate()
def list_orders():
    subc_filter = (request.args.get("subcontractor_id")
                   or request.args.get("subcontractorId"))
    with get_session() as session:
        statement = (
            select(Order)
            .options(
                joinedload(Order.estimate_costs),
                joinedload(Order.subcontractor),
                joinedload(Order.financial_docs),
            )
        )
        if subc_filter:
            statement = statement.where(Order.ID_Subcontractor == subc_filter)
        statement = _scope_orders_statement(statement)
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        order_data = [
            add_relationships(
                order, ["estimate_costs", "subcontractor", "financial_docs"])
            for order in results
        ]

        return order_data, 200


@order_bp.get("/<id_order>")
@handle_exceptions()
def get_order(id_order):

    with get_session() as session:
        statement = (
            select(Order)
            .options(
                joinedload(Order.estimate_costs),
                joinedload(Order.subcontractor),
                joinedload(Order.financial_docs),
            )
            .where(Order.ID_Order == id_order)
        )

        statement = _scope_orders_statement(statement)
        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Order no encontrado.", "order_not_found", 404)

        order_data = add_relationships(
            obj, ["estimate_costs", "subcontractor", "financial_docs"])

        return order_data, 200


@order_bp.get("/subcontractor/<id_subcontractor>/job/<id_job>")
@handle_exceptions()
@paginate()
def get_orders_by_subc_and_job(id_subcontractor, id_job):

    # Portal: un subcontratista solo puede consultar SUS orders (REG-110)
    from src.utils.middleware.auth.routes_protection import portal_scope
    p_role, p_id = portal_scope()
    if p_role == "subcontractor" and id_subcontractor != p_id:
        raise AppException("Forbidden", "forbidden", 403)

    with get_session() as session:

        job = session.exec(
            select(Job).where(Job.ID_Jobs == id_job)
        ).first()

        if not job:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        conditions = [
            Order.estimate_costs.any(EstimateCost.ID_Jobs == id_job)
        ]

        if job.podio_item_id:
            conditions.append(Order.job_podio_id == job.podio_item_id)

        statement = (
            select(Order)
            .options(
                joinedload(Order.estimate_costs).joinedload(EstimateCost.job),
                joinedload(Order.subcontractor),
                joinedload(Order.change_orders),
                joinedload(Order.financial_docs),
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
                ["estimate_costs.job", "subcontractor", "change_orders", "financial_docs"]
            )
            for order in results
        ]

        return orders_data, 200


@order_bp.get("/job/<job_podio_id>")
@handle_exceptions()
@paginate()
def get_orders_by_job(job_podio_id):
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
        statement = _scope_orders_statement(statement)

        if subc_id:
            statement = statement.where(Order.ID_Subcontractor == subc_id)

        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        orders_data = [
            add_relationships(
                order, ["estimate_costs", "subcontractor", "change_orders"])
            for order in results
        ]

        return orders_data, 200


@order_bp.get("/job-id/<id_job>")
@handle_exceptions()
@paginate()
def get_orders_by_job_id(id_job):
    with get_session() as session:
        statement = (
            select(Order)
            .join(Order.estimate_costs)
            .options(
                joinedload(Order.estimate_costs),
                joinedload(Order.subcontractor),
                joinedload(Order.change_orders),
            )
            .where(EstimateCost.ID_Jobs == id_job)
        )
        statement = _scope_orders_statement(statement)

        results = session.exec(statement).unique().all()
        if not results:
            return [], 200

        orders_data = [
            add_relationships(
                order, ["estimate_costs", "subcontractor", "change_orders"])
            for order in results
        ]

        return orders_data, 200


# --------------- RUTAS POST, PATCH AND DELETE ----------#

@order_bp.post("/")
@handle_exceptions()
@audit("Order created", entity_type="Order", id_from="response", job_id_from="body")
def create_order():

    data = request.get_json()
    create_order = OrderCreate.model_validate(data)
    # Excluir campos que no pertenecen al modelo Order (relaciones o auxiliares)
    order_data = create_order.model_dump(
        exclude={"estimate_cost_ids", "ID_FinancialDoc"},
        exclude_unset=False,
        exclude_none=False
    )
    obj = Order(**order_data)
        
    # 🔥 FIX RACE CONDITION TEMPRANO 🔥
    # Registrar el evento apenas entra el request. Así interceptamos cualquier webhook
    # que Podio ya haya despachado debido a acciones del frontend (ej: vincular subcontractor).
    if obj.job_podio_id:
        register_event(obj.job_podio_id)

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    if sync_podio and not year:
        raise AppException(
            "El parámetro 'year' es obligatorio cuando sync_podio=true.",
            "missing_year",
            400)

    with get_session() as session:
        # ----------- 💾 GENERAR ID Y PRE-GUARDAR
        new_id = generate_custom_id(session, Order, "ID_Order", "ORD")
        obj.ID_Order = new_id
        session.add(obj)

        # ----------- 🔵 ASOCIAR ESTIMATE COSTS (SI VIENEN)
        if create_order.estimate_cost_ids:
            statement = select(EstimateCost).where(
                EstimateCost.ID_EstimateCost.in_(create_order.estimate_cost_ids)
            )
            costs = session.exec(statement).all()
            obj.estimate_costs = list(costs)
            
        session.flush()

        # ----------- 🔗 VINCULAR FINANCIAL DOCUMENT (BILL) SI VIENE
        if create_order.ID_FinancialDoc:
            statement_fd = select(FinancialDocument).where(
                FinancialDocument.ID_FinancialDoc == create_order.ID_FinancialDoc
            )
            fd = session.exec(statement_fd).first()
            if fd:
                fd.ID_Order = obj.ID_Order
                session.add(fd)
            else:
                raise AppException("FinancialDocument (Bill) no encontrado.", "financial_doc_not_found", 404)

        session.flush()

        # ── Recálculo inicial de fórmulas de la Order ──────────────────────
        recalculate_order_formulas(obj.ID_Order, session)
        session.refresh(obj) # Asegurar recargar los valores calculados en memoria

        # VALIDACIÓN: No permitir órdenes con fórmula 0
        if not obj.Formula or obj.Formula == 0:
            raise AppException(
                "No se puede crear una Order con fórmula 0 o sin estimate costs asociados.",
                "invalid_formula_zero",
                400
            )

        # ----------- 🟢 SINCRONIZAR EN PODIO (SI APLICA)
        if sync_podio:
            if not obj.job_podio_id:
                raise AppException(
                    "job_podio_id es obligatorio cuando sync_podio=true",
                    "missing_job_podio_id",
                    400
                )

            # Flush eliminado, se hará el commit completo más adelante

            job = session.exec(
                select(Job).where(Job.podio_item_id == obj.job_podio_id)
            ).first()

            if not job:
                raise AppException("Job not found", "job_not_found", 404)

            if not job.Job_type:
                raise AppException(
                    "El Job no tiene Job_type definido",
                    "missing_job_type",
                    400)

            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type,
                year=year)

            podio_job = podio_service.get_item(obj.job_podio_id)
            raw_fields = podio_job.get("fields", {})
            podio_job_fields = normalize_podio_fields(raw_fields)

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

            # 🔥 FIX RACE CONDITION 🔥
            # Guardamos la orden localmente (ya tiene tech_field) ANTES de avisar a Podio.
            # Esto evita que si hay webhooks despachados previamente (como la vinculación 
            # del subcontratista desde el frontend) que lleguen concurrentemente a este endpoint,
            # puedan no encontrar la orden y dupliquen el slot.
            try:
                session.commit()
            except Exception as db_err:
                session.rollback()
                raise AppException("Error guardando temporalmente la orden.", "db_tmp_save_error", 500)

            try:
                podio_service.update_item(obj.job_podio_id, payload)

            except Exception as podio_err:
                # Rollback compensatorio
                session.delete(obj)
                session.commit()
                raise AppException(
                    f"No se pudo sincronizar Order con Podio: {podio_err}",
                    "podio_sync_failed",
                    400
                )

        else:
            # Si sync_podio es falso, aplicamos el guardado normal aquí
            save_with_retry(session, obj)

        logger.info(
            "✅ Order creado | order_id=%s | job_item_id=%s",
            obj.ID_Order,
            obj.job_podio_id
        )

        # ── Recálculo automático del Job asociado ─────────────────────────
        job_id_for_calc = None
        if obj.job_podio_id:
            linked_job = session.exec(
                select(Job).where(Job.podio_item_id == obj.job_podio_id)
            ).first()
            job_id_for_calc = linked_job.ID_Jobs if linked_job else None

        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        # Log en timeline del Subcontractor si la orden tiene uno asignado
        if obj.ID_Subcontractor:
            member_id = actor_member_id()
            log_activity(
                session,
                action="Order created",
                entity_id=obj.ID_Subcontractor,
                entity_type="Subcontractor",
                job_id=job_id_for_calc,
                member_id=member_id,
                description=f"Order: {obj.Title or obj.ID_Order}",
                source=SOURCE_APP,
            )
            session.commit()

            # REG-142: notificar la nueva orden al subcontratista (no bloqueante)
            try:
                from src.models.SubcontractorModel import Subcontractor
                from src.services.email_service import send_new_order_or_co
                sub = session.get(Subcontractor, obj.ID_Subcontractor)
                if sub and sub.Email_Address:
                    send_new_order_or_co(
                        sub.Email_Address,
                        sub.Name or sub.Organization or "Subcontractor",
                        "order", obj.Title or obj.ID_Order, job_id_for_calc)
            except Exception:
                logger.exception("No se pudo notificar la nueva orden")

        return obj.model_dump(), 201


@order_bp.patch("/<id_order>")
@handle_exceptions()
@audit("Order updated", entity_type="Order", id_param="id_order", job_id_from="response")
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
            
        # 🔥 FIX RACE CONDITION TEMPRANO 🔥
        if order.job_podio_id:
            register_event(order.job_podio_id)

        # Capturar job_id ANTES de modificar el objeto (por si job_podio_id cambiara)
        job_id_for_calc = None
        if order.job_podio_id:
            linked_job = session.exec(
                select(Job).where(Job.podio_item_id == order.job_podio_id)
            ).first()
            job_id_for_calc = linked_job.ID_Jobs if linked_job else None

        # Extract fields not in OrderUpdate before validation
        financial_doc_id   = data.get("ID_FinancialDoc")
        handle_bill_update = "ID_FinancialDoc" in data

        update_order = OrderUpdate.model_validate(data)
        update_data_dict = update_order.model_dump(exclude_unset=True)
        update_data_dict.pop("job_podio_id", None)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():
            setattr(order, key, value)

        # ----------- 🔗 ACTUALIZAR BILL VINCULADO (SI SE ENVIÓ ID_FinancialDoc)
        if handle_bill_update:
            current_bills = session.exec(
                select(FinancialDocument).where(FinancialDocument.ID_Order == id_order)
            ).all()
            for bill in current_bills:
                bill.ID_Order = None
                session.add(bill)
            if financial_doc_id:
                new_bill = session.exec(
                    select(FinancialDocument).where(FinancialDocument.ID_FinancialDoc == financial_doc_id)
                ).first()
                if new_bill:
                    new_bill.ID_Order = id_order
                    session.add(new_bill)
                else:
                    raise AppException("FinancialDocument (Bill) no encontrado.", "financial_doc_not_found", 404)

        # ----------- 🟢 ACTUALIZAR EN PODIO (SI APLICA)
        if sync_podio:
            if not order.job_podio_id:
                raise AppException(
                    "job_podio_id es obligatorio cuando sync_podio=true",
                    "missing_job_podio_id",
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

            payload = map_order_patch_to_podio(order, job.Job_type, session)

            try:
                if payload:
                    podio_service.update_item(order.job_podio_id, payload)

            except Exception as podio_err:
                raise AppException(
                    f"No se pudo sincronizar Order con Podio: {podio_err}",
                    "podio_sync_failed",
                    400
                )

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, order)

        logger.info("🔄 Order actualizado | order_id=%s", id_order)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        return order.model_dump(), 200


@order_bp.delete("/<id_order>")
@handle_exceptions()
@audit("Order deleted", entity_type="Order", id_param="id_order", job_id_from="body")
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
            
        # 🔥 FIX RACE CONDITION TEMPRANO 🔥
        if order.job_podio_id:
            register_event(order.job_podio_id)

        # Capturar job_id ANTES de borrar — después el objeto ya no tiene relaciones
        job_id_for_calc = None
        if order.job_podio_id:
            linked_job = session.exec(
                select(Job).where(Job.podio_item_id == order.job_podio_id)
            ).first()
            job_id_for_calc = linked_job.ID_Jobs if linked_job else None

        # ----------- 🟢 BORRAR EN PODIO (SI APLICA)
        if sync_podio:
            if not order.job_podio_id:
                raise AppException(
                    "job_podio_id es obligatorio cuando sync_podio=true",
                    "missing_job_podio_id",
                    400
                )

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

            except Exception as podio_err:
                raise AppException(
                    f"No se pudo sincronizar Order con Podio: {podio_err}",
                    "podio_sync_failed",
                    400
                )

        # Capturar datos del subcontractor ANTES de borrar
        subc_id_for_log    = order.ID_Subcontractor
        order_title_for_log = order.Title or id_order

        # ----------- 🧹 DESVINCULAR ESTIMATE COSTS (Evitar fallos de Foreing Key)
        costs = session.exec(
            select(EstimateCost).where(EstimateCost.ID_Order == order.ID_Order)
        ).all()
        for c in costs:
            c.ID_Order = None
            session.add(c)
        # Hacemos flush para asegurar que se removieron de la tabla antes del DELETE
        session.flush()

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, order)

        logger.info("🗑️ Order eliminado | order_id=%s", id_order)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        # Log en timeline del Subcontractor si la orden tenía uno asignado
        if subc_id_for_log:
            member_id = actor_member_id()
            log_activity(
                session,
                action="Order deleted",
                entity_id=subc_id_for_log,
                entity_type="Subcontractor",
                job_id=job_id_for_calc,
                member_id=member_id,
                description=f"Order: {order_title_for_log}",
                source=SOURCE_APP,
            )
            session.commit()

        return jsonify({
            "message": f"Order {id_order} eliminado correctamente"
        }), 200
