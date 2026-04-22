# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.PurchaseModel import Purchase, PurchaseCreate, PurchaseUpdate
from ..models.PurchaseOrderModel import PurchaseOrder
from ..models.PurchaseOrderItemModel import PurchaseOrderItem
from ..models.EstimateCostModel import EstimateCost
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from sqlalchemy import func, or_
from src.utils.job_calculator import recalculate_and_apply
from src.utils.middleware.auth.routes_protection import require_permission


# Blueprint de Purchase:
purchase_bp = Blueprint("purchase_blueprint",
                        __name__, url_prefix="/purchase")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#

@purchase_bp.get("/")
@require_permission("purchase:read")
@paginate()
def list_purchases():
    try:
        with get_session() as session:

            statement = (
                select(Purchase)
                .options(
                    joinedload(Purchase.job),
                    joinedload(Purchase.member),
                    joinedload(Purchase.purchase_orders).joinedload(
                        PurchaseOrder.porder_items),
                    joinedload(Purchase.suppliers),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            purc_data = [
                add_relationships(
                    purc, ["job", "member", "purchase_orders", "purchase_orders.porder_items", "suppliers"])
                for purc in results
            ]

            return purc_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar purchases: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar purchases: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


@purchase_bp.get("/table")
@require_permission("purchase:read")
def list_purchases_table():
    try:
        q_param = request.args.get("q",       "").strip()
        status_param = request.args.get("status",  "").strip()
        job_id_param = request.args.get("job_id",  "").strip()
        page = max(1, int(request.args.get("page",  1)))
        limit = min(100, max(1, int(request.args.get("limit", 20))))
        offset = (page - 1) * limit

        with get_session() as session:
            stmt = select(
                Purchase.ID_Purchase,
                Purchase.Selling_rep,
                Purchase.Description,
                Purchase.PickUp_person,
                Purchase.Delivery_location,
                Purchase.Status,
                Purchase.Return_request,
                Purchase.Return_status,
                Purchase.Total_spending,
                Purchase.ID_Jobs,
                Purchase.ID_Member,
                Purchase.podio_item_id,
            )

            if q_param:
                like = f"%{q_param}%"
                stmt = stmt.where(
                    or_(
                        Purchase.ID_Purchase.ilike(like),
                        Purchase.Selling_rep.ilike(like),
                        Purchase.Description.ilike(like),
                        Purchase.PickUp_person.ilike(like),
                        Purchase.Delivery_location.ilike(like),
                    )
                )

            if status_param:
                stmt = stmt.where(Purchase.Status == status_param)

            if job_id_param:
                stmt = stmt.where(Purchase.ID_Jobs == job_id_param)

            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = session.exec(count_stmt).one()

            stmt = stmt.order_by(Purchase.ID_Purchase.desc()
                                 ).offset(offset).limit(limit)
            rows = session.exec(stmt).all()

            from ..models.PurchaseOrderModel import PurchaseOrder
            from ..models.PurchaseOrderItemModel import PurchaseOrderItem

            purchase_ids = [r.ID_Purchase for r in rows]

            order_counts = {}
            item_counts = {}

            if purchase_ids:
                order_count_stmt = (
                    select(PurchaseOrder.ID_Purchase, func.count(
                        PurchaseOrder.ID_PurchaseOrder).label("cnt"))
                    .where(PurchaseOrder.ID_Purchase.in_(purchase_ids))
                    .group_by(PurchaseOrder.ID_Purchase)
                )
                for pid, cnt in session.exec(order_count_stmt).all():
                    order_counts[pid] = cnt

                item_count_stmt = (
                    select(PurchaseOrder.ID_Purchase, func.count(
                        PurchaseOrderItem.ID_PurchaseOrderItem).label("cnt"))
                    .join(PurchaseOrderItem, PurchaseOrderItem.ID_PurchaseOrder == PurchaseOrder.ID_PurchaseOrder)
                    .where(PurchaseOrder.ID_Purchase.in_(purchase_ids))
                    .group_by(PurchaseOrder.ID_Purchase)
                )
                for pid, cnt in session.exec(item_count_stmt).all():
                    item_counts[pid] = cnt

            results = []
            for r in rows:
                pid = r.ID_Purchase
                results.append({
                    "ID_Purchase":       pid,
                    "Selling_rep":       r.Selling_rep,
                    "Description":       r.Description,
                    "PickUp_person":     r.PickUp_person,
                    "Delivery_location": r.Delivery_location,
                    "Status":            r.Status,
                    "Return_request":    r.Return_request,
                    "Return_status":     r.Return_status,
                    "Total_spending":    float(r.Total_spending) if r.Total_spending is not None else None,
                    "ID_Jobs":           r.ID_Jobs,
                    "ID_Member":         r.ID_Member,
                    "podio_item_id":     r.podio_item_id,
                    "order_count":       order_counts.get(pid, 0),
                    "item_count":        item_counts.get(pid, 0),
                })

            return jsonify({
                "results": results,
                "total":   total,
                "page":    page,
                "limit":   limit,
            }), 200

    except Exception as e:
        print(f"Error en /purchase/table: {e}")
        return jsonify({"detail": "Error interno del servidor.", "code": "internal_error"}), 500


@purchase_bp.get("/<id_purchase>")
@require_permission("purchase:read")
def get_purchase(id_purchase):
    try:
        with get_session() as session:

            statement = (
                select(Purchase)
                .options(
                    joinedload(Purchase.job),
                    joinedload(Purchase.member),
                    joinedload(Purchase.purchase_orders).joinedload(
                        PurchaseOrder.porder_items),
                    joinedload(Purchase.suppliers),
                )
                .where(Purchase.ID_Purchase == id_purchase)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Purchase not found"}), 404

            purc_data = add_relationships(
                obj, ["job", "member", "purchase_orders", "purchase_orders.porder_items", "suppliers"])

            return jsonify(purc_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar purchase {id_purchase}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar purchase: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE ----------#

@purchase_bp.post("/")
@require_permission("purchase:create")
def create_purchase():
    try:
        data = request.get_json()
        create_purchase = PurchaseCreate.model_validate(data)
        obj = Purchase(**create_purchase.model_dump())

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(session, Purchase, "ID_Purchase", "IH")
            obj.ID_Purchase = new_id

            save_with_retry(session, obj)

            # ── Recálculo automático del Job asociado ─────────────────────
            if obj.ID_Jobs:
                recalculate_and_apply(obj.ID_Jobs, session)
                session.commit()
            # ─────────────────────────────────────────────────────────────

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:
        session.rollback()
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un purchase con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        session.rollback()
        print(f"Error de base de datos al crear purchase: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        print(f"Error inesperado durante la creación de purchase: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


@purchase_bp.patch("/<id_purchase>")
@require_permission("purchase:update")
def update_purchase(id_purchase):
    session = None
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Purchase, id_purchase)
            if not obj:
                return jsonify({"error": "Purchase not found"}), 404

            # Capturar job_id antes de modificar por si cambiara
            job_id_for_calc = obj.ID_Jobs

            update_purchase = PurchaseUpdate.model_validate(data)
            update_data_dict = update_purchase.model_dump(exclude_unset=True)

            for key, value in update_data_dict.items():
                setattr(obj, key, value)

            save_with_retry(session, obj)

            # ── Si ID_Jobs se acaba de asignar, actualizar EstimateCosts huérfanos ──
            # Los EstimateCosts se crean cuando se crean los items, pero en ese momento
            # la Purchase puede no tener Job vinculado. Aquí los sincronizamos.
            new_job_id = update_data_dict.get("ID_Jobs")
            if new_job_id and new_job_id != job_id_for_calc:
                # Recolectar todos los IDs de items de esta Purchase
                orders_stmt = select(PurchaseOrder).where(
                    PurchaseOrder.ID_Purchase == id_purchase
                )
                orders = session.exec(orders_stmt).all()
                item_ids = []
                for order in orders:
                    items_stmt = select(PurchaseOrderItem).where(
                        PurchaseOrderItem.ID_PurchaseOrder == order.ID_PurchaseOrder
                    )
                    items = session.exec(items_stmt).all()
                    item_ids.extend([it.ID_PurchaseOrderItem for it in items])

                if item_ids:
                    estimates_stmt = select(EstimateCost).where(
                        EstimateCost.Cost_code.in_(item_ids)
                    )
                    orphaned = session.exec(estimates_stmt).all()
                    for est in orphaned:
                        est.ID_Jobs = new_job_id
                        save_with_retry(session, est)
            # ─────────────────────────────────────────────────────────────────────

            # ── Recálculo automático del Job asociado ─────────────────────
            if job_id_for_calc:
                recalculate_and_apply(job_id_for_calc, session)
            if new_job_id and new_job_id != job_id_for_calc:
                recalculate_and_apply(new_job_id, session)
            session.commit()
            # ─────────────────────────────────────────────────────────────

            return jsonify(obj.model_dump()), 200

    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de purchase inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un purchase con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar purchase: {db_error}")
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
        print(f"Error inesperado al actualizar purchase: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


@purchase_bp.delete("/<id_purchase>")
@require_permission("purchase:delete")
def delete_purchase(id_purchase):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Purchase, id_purchase)
            if not obj:
                return jsonify({"error": "Purchase not found"}), 404

            # Capturar job_id ANTES de borrar — después el objeto ya no tiene relaciones
            job_id_for_calc = obj.ID_Jobs

            delete_with_retry(session, obj)

            # ── Recálculo automático del Job asociado ─────────────────────
            if job_id_for_calc:
                recalculate_and_apply(job_id_for_calc, session)
                session.commit()
            # ─────────────────────────────────────────────────────────────

            return jsonify({"message": f"Deleted Purchase {id_purchase}"}), 200

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el purchase porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar purchase: {db_error}")
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
        print(f"Error inesperado al eliminar purchase: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
