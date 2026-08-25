# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.PurchaseOrderModel import PurchaseOrder, POrderCreate, POrderUpdate
from ..models.PurchaseOrderItemModel import PurchaseOrderItem
from ..models.PurchaseModel import Purchase
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from src.utils.job_calculator import recalculate_and_apply


# Blueprint de PurchaseOrder:
purchase_order_bp = Blueprint("purchase_order_blueprint",
                              __name__, url_prefix="/purchase_order")


# ─── Helper ───────────────────────────────────────────────────────────────────
# Used when an entire PurchaseOrder is deleted. Its items are cascade-deleted,
# so we recompute Total_spending on the parent Purchase from whatever orders remain.

def _recalculate_purchase_total_by_purchase_id(purchase_id: str, session) -> None:
    purchase = session.get(Purchase, purchase_id)
    if not purchase:
        return

    all_items = session.exec(
        select(PurchaseOrderItem)
        .join(PurchaseOrder,
              PurchaseOrderItem.ID_PurchaseOrder == PurchaseOrder.ID_PurchaseOrder)
        .where(PurchaseOrder.ID_Purchase == purchase_id)
    ).all()

    purchase.Total_spending = sum(float(it.Purchase_value or 0) for it in all_items)
    session.add(purchase)

    if purchase.ID_Jobs:
        recalculate_and_apply(purchase.ID_Jobs, session)
        from src.utils.podio_job_sync import sync_job_to_podio
        # El recalculo se COMMITEA antes de salir a Podio. Un fallo de
        # sincronizacion no puede destruir datos locales que ya estaban bien:
        # `record_failed_sync` hace `session.rollback()` como primera
        # instruccion y se llevaba por delante los agregados recien
        # calculados, dejando el job con el total viejo y sus hijos nuevos.
        session.commit()
        sync_job_to_podio(purchase.ID_Jobs, session)


# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#

@purchase_order_bp.get("/")
@paginate()
def list_purchase_order():
    try:
        with get_session() as session:
            statement = (
                select(PurchaseOrder)
                .options(
                    joinedload(PurchaseOrder.purchase),
                    joinedload(PurchaseOrder.porder_items),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            fd_data = [add_relationships(fd, ["purchase", "porder_items"]) for fd in results]
            return fd_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar purchase order: {db_error}")
        return jsonify({"detail": "Error interno del servidor al consultar la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        print(f"Error inesperado al listar purchase order: {e}")
        return jsonify({"detail": "Error interno inesperado del servidor.", "code": "internal_error"}), 500


@purchase_order_bp.get("/<id_purchase_order>")
def get_purchase_order(id_purchase_order):
    try:
        with get_session() as session:
            statement = (
                select(PurchaseOrder)
                .options(
                    joinedload(PurchaseOrder.purchase),
                    joinedload(PurchaseOrder.porder_items),
                )
                .where(PurchaseOrder.ID_PurchaseOrder == id_purchase_order)
            )
            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "PurchaseOrder not found"}), 404

            return jsonify(add_relationships(obj, ["purchase", "porder_items"])), 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al buscar purchase order {id_purchase_order}: {db_error}")
        return jsonify({"detail": "Error interno del servidor al consultar la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        print(f"Error inesperado al listar purchase order: {e}")
        return jsonify({"detail": "Error interno inesperado del servidor.", "code": "internal_error"}), 500


# --------------- RUTAS POST, PATCH AND DELETE ----------#

# POST: no recalculation needed — a new empty order has no items yet
@purchase_order_bp.post("/")
def create_purchase_order():
    try:
        data = request.get_json()
        create_data = POrderCreate.model_validate(data)
        obj = PurchaseOrder.model_validate(create_data)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(session, PurchaseOrder, "ID_PurchaseOrder", "PO")
            obj.ID_PurchaseOrder = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:
        session.rollback()
        error_message = str(e)
        detail = "Ya existe un purchase order con este valor único." if "UNIQUE constraint failed" in error_message \
            else "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        session.rollback()
        print(f"Error de base de datos al crear purchase order: {db_error}")
        return jsonify({"detail": "Error interno del servidor al interactuar con la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        print(f"Error inesperado durante la creación de purchase order: {e}")
        return jsonify({"detail": "Ocurrió un error inesperado y no controlado en el servidor.", "code": "internal_error"}), 500


# PATCH: no recalculation needed — only metadata fields change
# (Order_title, Est_delivery_date, Order_confirmation), not Purchase_value
@purchase_order_bp.patch("/<id_purchase_order>")
def update_purchase_order(id_purchase_order):
    session = None
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(PurchaseOrder, id_purchase_order)
            if not obj:
                return jsonify({"error": "PurchaseOrder not found"}), 404

            update_data = POrderUpdate.model_validate(data)
            for key, value in update_data.model_dump(exclude_unset=True).items():
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    except ValidationError as e:
        return jsonify({"detail": "Error de validación: Datos de purchase order inválidos para la actualización.", "errors": e.errors()}), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": "Error de integridad: Ya existe un purchase order con estos valores únicos o faltan datos requeridos."}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar purchase order: {db_error}")
        return jsonify({"detail": "Error interno del servidor al interactuar con la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al actualizar purchase order: {e}")
        return jsonify({"detail": "Ocurrió un error inesperado y no controlado en el servidor.", "code": "internal_error"}), 500


# DELETE: items are cascade-deleted with the order, so we must recompute Total_spending
@purchase_order_bp.delete("/<id_purchase_order>")
def delete_purchase_order(id_purchase_order):
    session = None
    try:
        with get_session() as session:
            obj = session.get(PurchaseOrder, id_purchase_order)
            if not obj:
                return jsonify({"error": "PurchaseOrder not found"}), 404

            # Capture FK before delete
            purchase_id_for_calc = obj.ID_Purchase

            # ── Delete associated EstimateCost records for all items in this order ──
            from ..models.EstimateCostModel import EstimateCost
            items_stmt = select(PurchaseOrderItem).where(
                PurchaseOrderItem.ID_PurchaseOrder == id_purchase_order
            )
            items_to_delete = session.exec(items_stmt).all()
            item_ids = [it.ID_PurchaseOrderItem for it in items_to_delete]
            if item_ids:
                estimates_to_delete = session.exec(
                    select(EstimateCost).where(
                        EstimateCost.Cost_code.in_(item_ids)
                    )
                ).all()
                for est in estimates_to_delete:
                    delete_with_retry(session, est)

            delete_with_retry(session, obj)

            # ── Recalculate Purchase.Total_spending + Job.Gqm_total_materials_fees ──
            if purchase_id_for_calc:
                _recalculate_purchase_total_by_purchase_id(purchase_id_for_calc, session)
                session.commit()
            # ────────────────────────────────────────────────────────────────────────

            return jsonify({"message": f"Deleted PurchaseOrder {id_purchase_order}"}), 200

    except IntegrityError as e:
        if session:
            session.rollback()
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": "Error de integridad: No se puede eliminar el purchase order porque tiene registros relacionados."}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar purchase order: {db_error}")
        return jsonify({"detail": "Error interno del servidor al interactuar con la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al eliminar purchase order: {e}")
        return jsonify({"detail": "Ocurrió un error inesperado y no controlado en el servidor.", "code": "internal_error"}), 500