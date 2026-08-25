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

def _rechazar_si_no_cabe_otro_bdf(session, obj, id_excluir=None) -> None:
    """Impide aprobar mas BDF de los que Podio puede guardar.

    Podio tiene EXACTAMENTE `BDF_SLOTS` (3) huecos de Bldg_dept_fees, y
    `_build_bdf_array` trunca ahi. Un 4.o BDF aprobado nunca podria escribirse,
    y en el siguiente `item.update` el webhook veria 3 en Podio contra 4 aqui y
    lo BORRARIA — sin auditoria y sin soft-delete, o sea irrecuperable.

    Se rechaza en el alta en vez de dejar que un webhook destruya datos despues.
    """
    from sqlalchemy import func

    from src.utils.job_calculator import BDF_SLOTS

    if (obj.Cost_type or "").strip() != "BDF":
        return
    if (obj.Status or "").strip() != "Approved":
        return
    if not obj.ID_Jobs:
        return

    stmt = select(func.count(EstimateCost.ID_EstimateCost)).where(
        EstimateCost.ID_Jobs == obj.ID_Jobs,
        EstimateCost.Cost_type == "BDF",
        EstimateCost.Status == "Approved")
    if id_excluir:
        stmt = stmt.where(EstimateCost.ID_EstimateCost != id_excluir)

    ya_aprobados = session.exec(stmt).one()
    if ya_aprobados >= BDF_SLOTS:
        raise AppException(
            f"El job {obj.ID_Jobs} ya tiene {ya_aprobados} BDF aprobados y "
            f"Podio solo admite {BDF_SLOTS}. Aprobar otro lo dejaria fuera de "
            f"Podio y el siguiente webhook lo borraria de la base.",
            "bdf_slots_agotados", 409)


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
        _rechazar_si_no_cabe_otro_bdf(session, obj)
        obj.ID_EstimateCost = generate_custom_id(
            session, EstimateCost, "ID_EstimateCost", "EST")
        save_with_retry(session, obj)

        # ── Recálculo automático del Job asociado ─────────────────────────
        if obj.ID_Jobs:
            recalculate_and_apply(obj.ID_Jobs, session)
            from src.utils.podio_job_sync import sync_job_to_podio
            # El recalculo se COMMITEA antes de salir a Podio. Un fallo de
            # sincronizacion no puede destruir datos locales que ya estaban bien:
            # `record_failed_sync` hace `session.rollback()` como primera
            # instruccion y se llevaba por delante los agregados recien
            # calculados, dejando el job con el total viejo y sus hijos nuevos.
            session.commit()
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

        update_data = EstimateUpdate.model_validate(
            data).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(obj, key, value)
        # Tras aplicar los cambios: un PATCH que pone Status=Approved es
        # exactamente el camino por el que se cuela el 4.o BDF.
        _rechazar_si_no_cabe_otro_bdf(session, obj, id_excluir=id_estimate)
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
            # El recalculo se COMMITEA antes de salir a Podio. Un fallo de
            # sincronizacion no puede destruir datos locales que ya estaban bien:
            # `record_failed_sync` hace `session.rollback()` como primera
            # instruccion y se llevaba por delante los agregados recien
            # calculados, dejando el job con el total viejo y sus hijos nuevos.
            session.commit()
            sync_job_to_podio(job_id_for_calc, session)
            session.commit()

        # REG-145: si el costo se reasignó a otro job, recalcular TAMBIÉN el
        # nuevo (mismo patrón que Purchase.py) — antes solo se recalculaba el
        # viejo y el nuevo quedaba con agregados desactualizados.
        if obj.ID_Jobs and obj.ID_Jobs != job_id_for_calc:
            recalculate_and_apply(obj.ID_Jobs, session)
            from src.utils.podio_job_sync import sync_job_to_podio
            # El recalculo se COMMITEA antes de salir a Podio. Un fallo de
            # sincronizacion no puede destruir datos locales que ya estaban bien:
            # `record_failed_sync` hace `session.rollback()` como primera
            # instruccion y se llevaba por delante los agregados recien
            # calculados, dejando el job con el total viejo y sus hijos nuevos.
            session.commit()
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
            # El recalculo se COMMITEA antes de salir a Podio. Un fallo de
            # sincronizacion no puede destruir datos locales que ya estaban bien:
            # `record_failed_sync` hace `session.rollback()` como primera
            # instruccion y se llevaba por delante los agregados recien
            # calculados, dejando el job con el total viejo y sus hijos nuevos.
            session.commit()
            sync_job_to_podio(job_id_for_calc, session)
            session.commit()
        # ─────────────────────────────────────────────────────────────────

        return jsonify({"message": f"Deleted Estimate Cost {id_estimate}"}), 200
