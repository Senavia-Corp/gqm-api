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
from src.utils.job_calculator import recalculate_and_apply  # ← NEW

estimate_bp = Blueprint("estimate_blueprint", __name__, url_prefix="/estimate")


# ── GETs ─────────────────────────────────────────────────────────────────────

@estimate_bp.get("/")
@handle_exceptions()
@paginate()
def list_estimates():
    with get_session() as session:
        results = session.exec(
            select(EstimateCost).options(joinedload(EstimateCost.job), joinedload(EstimateCost.order))
        ).unique().all()
        if not results: return [], 200
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
        if not obj: raise AppException("Estimate Cost not found", "estimate_not_found", 404)
        return add_relationships(obj, ["job", "order"]), 200


# ── WRITE routes ──────────────────────────────────────────────────────────────

@estimate_bp.post("/")
@handle_exceptions()
@audit("Estimate Cost created", job_id_from="body")
def create_estimate():
    data            = request.get_json()
    create_estimate = EstimateCreate.model_validate(data)
    obj             = EstimateCost(**create_estimate.model_dump(exclude_unset=False, exclude_none=False))

    with get_session() as session:
        obj.ID_EstimateCost = generate_custom_id(session, EstimateCost, "ID_EstimateCost", "EST")
        save_with_retry(session, obj)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if obj.ID_Jobs:
            recalculate_and_apply(obj.ID_Jobs, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        return obj.model_dump(), 201


@estimate_bp.patch("/<id_estimate>")
@handle_exceptions()
@audit("Estimate Cost updated", id_param="id_estimate", job_id_from="response")
def update_estimate(id_estimate):
    data = request.get_json()
    with get_session() as session:
        obj = session.get(EstimateCost, id_estimate)
        if not obj: raise AppException("Estimate Cost not found", "estimate_not_found", 404)

        # Capturar job_id antes de modificar por si ID_Jobs cambiara
        job_id_for_calc = obj.ID_Jobs

        update_data = EstimateUpdate.model_validate(data).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(obj, key, value)
        save_with_retry(session, obj)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        return obj.model_dump(), 200


@estimate_bp.delete("/<id_estimate>")
@handle_exceptions()
@audit("Estimate Cost deleted", id_param="id_estimate", job_id_from="response")
def delete_estimate(id_estimate):
    with get_session() as session:
        obj = session.get(EstimateCost, id_estimate)
        if not obj: raise AppException("Estimate Cost not found", "estimate_not_found", 404)

        # Capturar job_id ANTES de borrar — después el objeto ya no tiene relaciones
        job_id_for_calc = obj.ID_Jobs

        delete_with_retry(session, obj)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        return jsonify({"message": f"Deleted Estimate Cost {id_estimate}"}), 200