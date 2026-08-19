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

def _reservar_hueco(session, obj):
    """Marca en el coste el `external_id` que va a ocupar en Podio."""
    from src.utils import podio_slots

    if not obj.ID_Jobs or (obj.Status or "").strip() != "Approved":
        return None
    fam = podio_slots.familia_de_coste(obj.Cost_type)
    if fam is None:
        return None
    return podio_slots.reservar(session, fam, obj.ID_Jobs, obj)


def _liberar_hueco(session, obj):
    """Suelta el hueco de un coste que se desaprueba. Devuelve el `external_id`
    liberado para vaciarlo en Podio explícitamente."""
    from src.utils import podio_slots

    return podio_slots.liberar(session, obj)


def _exigir_hueco_libre(session, obj):
    """Un coste aprobado que no cabe en Podio se rechaza ANTES de guardarlo.

    Podio tiene 3 huecos de BD fees y 13 de materiales, y hasta ahora un 4.º BD
    fee aprobado se aceptaba con 201 y luego lo BORRABA el primer webhook que
    tocara el job — daba igual el motivo (reproducido cambiando sólo
    `job-status`). Mismo contrato que los change orders, que ya responden 400
    `no_available_order_slot` sin guardar nada.

    Sólo cuentan los APROBADOS: un coste `Estimated` no toca los huecos (V9).
    """
    from src.utils import podio_slots

    if not obj.ID_Jobs or (obj.Status or "").strip() != "Approved":
        return
    fam = podio_slots.familia_de_coste(obj.Cost_type)
    if fam is None:
        return
    libres = podio_slots.libres_en_bd(
        session, fam, obj.ID_Jobs, excluir_pk=obj.ID_EstimateCost)
    if not libres:
        raise AppException(
            f"No queda hueco en Podio para otro coste de tipo {obj.Cost_type}: "
            f"la app sólo tiene {len(fam.external_ids)} y ya están ocupados.",
            "no_available_slot", 400)


@estimate_bp.get("/")
@handle_exceptions()
@paginate()
def list_estimates():
    job_id = request.args.get("job_id") or request.args.get("jobId")
    unassigned = request.args.get("unassigned", "false").lower() == "true"
    with get_session() as session:
        statement = select(EstimateCost).options(
            joinedload(EstimateCost.job), joinedload(EstimateCost.order))
        if job_id:
            statement = statement.where(EstimateCost.ID_Jobs == job_id)
        if unassigned:
            statement = statement.where(EstimateCost.ID_Order.is_(None))
        results = session.exec(statement).unique().all()
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
    data = request.get_json() or {}
    # REG-094: alias temporal — el API acepta Quantity y lo mapea a la
    # columna histórica Quatity (rename real de columna = fase 2)
    if "Quantity" in data and "Quatity" not in data:
        data["Quatity"] = data.pop("Quantity")
    create_estimate = EstimateCreate.model_validate(data)
    obj = EstimateCost(
        **create_estimate.model_dump(exclude_unset=False, exclude_none=False))

    # BDF and Rent costs start as Estimated by default (quoted, not yet confirmed)
    if (obj.Cost_type or "").strip() in ("BDF", "Rent") and not (obj.Status or "").strip():
        obj.Status = "Estimated"

    with get_session() as session:
        obj.ID_EstimateCost = generate_custom_id(
            session, EstimateCost, "ID_EstimateCost", "EST")
        _exigir_hueco_libre(session, obj)
        _reservar_hueco(session, obj)
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
    data = request.get_json() or {}
    if "Quantity" in data and "Quatity" not in data:  # REG-094 alias
        data["Quatity"] = data.pop("Quantity")
    with get_session() as session:
        obj = session.get(EstimateCost, id_estimate)
        if not obj:
            raise AppException("Estimate Cost not found",
                               "estimate_not_found", 404)

        # Capturar job_id antes de modificar por si ID_Jobs cambiara
        job_id_for_calc = obj.ID_Jobs
        old_order_id = obj.ID_Order

        estado_antes = (obj.Status or "").strip()
        update_data = EstimateUpdate.model_validate(
            data).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(obj, key, value)

        # El hueco se toma al APROBAR y se suelta al desaprobar, no al crear.
        estado_ahora = (obj.Status or "").strip()
        slots_a_limpiar = []
        if estado_ahora == "Approved" and estado_antes != "Approved":
            _exigir_hueco_libre(session, obj)
            _reservar_hueco(session, obj)
        elif estado_antes == "Approved" and estado_ahora != "Approved":
            libre = _liberar_hueco(session, obj)
            if libre:
                slots_a_limpiar.append(libre)

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
            sync_job_to_podio(job_id_for_calc, session, limpiar_slots=slots_a_limpiar)
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
        # y el hueco que ocupaba, para vaciarlo en Podio de forma EXPLICITA
        slot_liberado = getattr(obj, "podio_field", None)

        delete_with_retry(session, obj)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if job_id_for_calc:
            recalculate_and_apply(job_id_for_calc, session)
            from src.utils.podio_job_sync import sync_job_to_podio
            sync_job_to_podio(job_id_for_calc, session,
                              limpiar_slots=[slot_liberado] if slot_liberado else None)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        return jsonify({"message": f"Deleted Estimate Cost {id_estimate}"}), 200
