from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.EstimateCostModel import EstimateCost, EstimateCreate, EstimateUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from src.utils.audit import audit
from src.utils.job_calculator import recalculate_and_apply, recalculate_order_formulas

estimate_bp = Blueprint("estimate_blueprint", __name__, url_prefix="/estimate")


# ── GETs ─────────────────────────────────────────────────────────────────────

@estimate_bp.get("/")
@handle_exceptions()
@paginate()
def list_estimates():
    with get_session() as session:
        results = session.exec(
            select(EstimateCost).options(joinedload(
                EstimateCost.job), joinedload(EstimateCost.order))
        ).unique().all()
        if not results:
            return [], 200
        return [add_relationships(e, ["job", "order"]) for e in results], 200


@estimate_bp.get("/<id_estimate>")
@handle_exceptions()
def get_estimates(id_estimate):
    with get_session() as session:
        obj = session.exec(
            select(EstimateCost)
            .options(joinedload(EstimateCost.job), joinedload(EstimateCost.order))
            .where(EstimateCost.ID_EstimateCost == id_estimate)
        ).unique().first()
        if not obj:
            raise AppException("Estimate Cost not found",
                               "estimate_not_found", 404)
        return add_relationships(obj, ["job", "order"]), 200


# --------------- RUTAS POST, PATCH AND DELETE ----------#

@estimate_bp.post("/")
@handle_exceptions()
@audit("Estimate Cost created", entity_type="EstimateCost", id_from="response", job_id_from="body")
def create_estimate():
    data = request.get_json()
    create_estimate = EstimateCreate.model_validate(data)
    obj = EstimateCost(
        **create_estimate.model_dump(exclude_unset=False, exclude_none=False))

    # BDF and Rent costs start as Estimated by default (quoted, not yet confirmed)
    if (obj.Cost_type or "").strip() in ("BDF", "Rent") and not (obj.Status or "").strip():
        obj.Status = "Estimated"

    with get_session() as session:
        obj.ID_EstimateCost = generate_custom_id(
            session, EstimateCost, "ID_EstimateCost", "EST")
        save_with_retry(session, obj)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if obj.ID_Jobs:
            recalculate_and_apply(obj.ID_Jobs, session)
            from src.utils.podio_job_sync import sync_job_to_podio
            sync_job_to_podio(obj.ID_Jobs, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        session.refresh(obj)
        return obj.model_dump(), 201


@estimate_bp.patch("/<id_estimate>")
@handle_exceptions()
@audit("Estimate Cost updated", entity_type="EstimateCost", id_param="id_estimate", job_id_from="body")
def update_estimate(id_estimate):
    data = request.get_json()
    with get_session() as session:
        obj = session.get(EstimateCost, id_estimate)
        if not obj:
            raise AppException("Estimate Cost not found",
                               "estimate_not_found", 404)

        # Capturar job_id antes de modificar por si ID_Jobs cambiara
        job_id_for_calc = obj.ID_Jobs
        old_order_id = obj.ID_Order

        update_data = EstimateUpdate.model_validate(
            data).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(obj, key, value)
        save_with_retry(session, obj)

        # ── [NUEVO] Recálculo automático de la Order asociada ────────
        if obj.ID_Order:
            recalculate_order_formulas(obj.ID_Order, session)
            session.commit()
        
        if old_order_id and old_order_id != obj.ID_Order:
            recalculate_order_formulas(old_order_id, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────

        # ── Recálculo automático del Job asociado ─────────────────────────
        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            from src.utils.podio_job_sync import sync_job_to_podio
            sync_job_to_podio(job_id_for_calc, session)
            session.commit()

        # REG-145: si el costo se reasignó a otro job, recalcular TAMBIÉN el
        # nuevo (mismo patrón que Purchase.py) — antes solo se recalculaba el
        # viejo y el nuevo quedaba con agregados desactualizados.
        if obj.ID_Jobs and obj.ID_Jobs != job_id_for_calc:
            recalculate_and_apply(obj.ID_Jobs, session)
            from src.utils.podio_job_sync import sync_job_to_podio
            sync_job_to_podio(obj.ID_Jobs, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        session.refresh(obj)
        return obj.model_dump(), 200


@estimate_bp.delete("/<id_estimate>")
@handle_exceptions()
@audit("Estimate Cost deleted", entity_type="EstimateCost", id_param="id_estimate", job_id_from="body")
def delete_estimate(id_estimate):
    with get_session() as session:
        obj = session.get(EstimateCost, id_estimate)
        if not obj:
            raise AppException("Estimate Cost not found",
                               "estimate_not_found", 404)

        # Capturar job_id ANTES de borrar — después el objeto ya no tiene relaciones
        job_id_for_calc = obj.ID_Jobs

        delete_with_retry(session, obj)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            from src.utils.podio_job_sync import sync_job_to_podio
            sync_job_to_podio(job_id_for_calc, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        return jsonify({"message": f"Deleted Estimate Cost {id_estimate}"}), 200
