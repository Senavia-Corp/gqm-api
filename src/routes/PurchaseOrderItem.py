# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.PurchaseOrderItemModel import PurchaseOrderItem, POrderItemCreate, POrderItemUpdate
from ..models.PurchaseOrderModel import PurchaseOrder
from ..models.PurchaseModel import Purchase
from ..models.EstimateCostModel import EstimateCost
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from src.utils.job_calculator import recalculate_and_apply


# Blueprint de PurchaseOrderItem:
purchase_order_item_bp = Blueprint("purchase_order_item_blueprint",
                                   __name__, url_prefix="/purchase_order_item")


# ─── Helper ───────────────────────────────────────────────────────────────────
# Recalculates Purchase.Total_spending as the sum of all Purchase_value across
# all items of all orders belonging to that Purchase.
# Then triggers recalculate_and_apply so that Gqm_total_materials_fees on the
# linked Job also stays in sync.
#
# Call AFTER saving/deleting the item, inside the same session.
# The caller is responsible for calling session.commit() afterwards.

def _recalculate_purchase_total(order_id: str, session) -> None:
    """
    order_id — ID_PurchaseOrder of the item that was just created/updated/deleted.
    """
    if not order_id:
        return

    # 1. Resolve Purchase from PurchaseOrder
    order = session.get(PurchaseOrder, order_id)
    if not order or not order.ID_Purchase:
        return

    purchase = session.get(Purchase, order.ID_Purchase)
    if not purchase:
        return

    # 2. Sum Purchase_value of every item across every order of this Purchase.
    #    Query fresh from DB — avoids stale ORM identity map cache.
    all_items = session.exec(
        select(PurchaseOrderItem)
        .join(PurchaseOrder,
              PurchaseOrderItem.ID_PurchaseOrder == PurchaseOrder.ID_PurchaseOrder)
        .where(PurchaseOrder.ID_Purchase == purchase.ID_Purchase)
    ).all()

    purchase.Total_spending = sum(float(it.Purchase_value or 0) for it in all_items)
    session.add(purchase)

    # 3. Propagate to Job so Gqm_total_materials_fees stays in sync
    if purchase.ID_Jobs:
        recalculate_and_apply(purchase.ID_Jobs, session)


# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#

@purchase_order_item_bp.get("/")
@paginate()
def list_po_items():
    try:
        with get_session() as session:
            statement = (
                select(PurchaseOrderItem)
                .options(joinedload(PurchaseOrderItem.purchase_order))
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            fd_data = [add_relationships(fd, ["purchase_order"]) for fd in results]
            return fd_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar purchase order items: {db_error}")
        return jsonify({"detail": "Error interno del servidor al consultar la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        print(f"Error inesperado al listar purchase order items: {e}")
        return jsonify({"detail": "Error interno inesperado del servidor.", "code": "internal_error"}), 500


@purchase_order_item_bp.get("/<id_po_item>")
def get_po_item(id_po_item):
    try:
        with get_session() as session:
            statement = (
                select(PurchaseOrderItem)
                .options(joinedload(PurchaseOrderItem.purchase_order))
                .where(PurchaseOrderItem.ID_PurchaseOrderItem == id_po_item)
            )
            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "PurchaseOrderItem not found"}), 404

            return jsonify(add_relationships(obj, ["purchase_order"])), 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al buscar purchase order item {id_po_item}: {db_error}")
        return jsonify({"detail": "Error interno del servidor al consultar la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        print(f"Error inesperado al listar purchase order item: {e}")
        return jsonify({"detail": "Error interno inesperado del servidor.", "code": "internal_error"}), 500


# --------------- RUTAS POST, PATCH AND DELETE ----------#

@purchase_order_item_bp.post("/")
def create_po_item():
    try:
        data = request.get_json()
        create_data = POrderItemCreate.model_validate(data)
        obj = PurchaseOrderItem.model_validate(create_data)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(session, PurchaseOrderItem, "ID_PurchaseOrderItem", "POI")
            obj.ID_PurchaseOrderItem = new_id

            save_with_retry(session, obj)

            # ── Auto-crear EstimateCost relacionado al PurchaseOrderItem ──
            job_id = None
            if obj.ID_PurchaseOrder:
                po = session.get(PurchaseOrder, obj.ID_PurchaseOrder)
                if po and po.ID_Purchase:
                    purchase_obj = session.get(Purchase, po.ID_Purchase)
                    if purchase_obj:
                        job_id = purchase_obj.ID_Jobs

            est_id = generate_custom_id(session, EstimateCost, "ID_EstimateCost", "EST")
            new_estimate = EstimateCost(
                ID_EstimateCost=est_id,
                Title=obj.Name,
                Unit_cost=obj.Quote_value,
                Builder_cost=obj.Quote_value,
                Description=obj.Quote_notes,
                Quatity=1.0,
                Cost_type="Material",
                ID_Jobs=job_id
            )
            save_with_retry(session, new_estimate)
            # ──────────────────────────────────────────────────────────────

            # ── Recalculate Purchase.Total_spending + Job.Gqm_total_materials_fees ──
            _recalculate_purchase_total(obj.ID_PurchaseOrder, session)
            session.commit()
            session.refresh(obj)
            # ────────────────────────────────────────────────────────────────────────

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:
        session.rollback()
        error_message = str(e)
        detail = "Ya existe un purchase order item con este valor único." if "UNIQUE constraint failed" in error_message \
            else "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        session.rollback()
        print(f"Error de base de datos al crear purchase order item: {db_error}")
        return jsonify({"detail": "Error interno del servidor al interactuar con la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        print(f"Error inesperado durante la creación de purchase order item: {e}")
        return jsonify({"detail": "Ocurrió un error inesperado y no controlado en el servidor.", "code": "internal_error"}), 500


@purchase_order_item_bp.patch("/<id_po_item>")
def update_po_item(id_po_item):
    session = None
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(PurchaseOrderItem, id_po_item)
            if not obj:
                return jsonify({"error": "PurchaseOrderItem not found"}), 404

            # Capture order_id before any potential changes
            order_id_for_calc = obj.ID_PurchaseOrder

            update_data = POrderItemUpdate.model_validate(data)
            for key, value in update_data.model_dump(exclude_unset=True).items():
                setattr(obj, key, value)

            save_with_retry(session, obj)

            # ── Recalculate Purchase.Total_spending + Job.Gqm_total_materials_fees ──
            _recalculate_purchase_total(order_id_for_calc, session)
            session.commit()
            session.refresh(obj)
            # ────────────────────────────────────────────────────────────────────────

            return jsonify(obj.model_dump()), 200

    except ValidationError as e:
        return jsonify({"detail": "Error de validación: Datos de purchase order item inválidos para la actualización.", "errors": e.errors()}), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": "Error de integridad: Ya existe un purchase order item con estos valores únicos o faltan datos requeridos."}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar purchase order item: {db_error}")
        return jsonify({"detail": "Error interno del servidor al interactuar con la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al actualizar purchase order item: {e}")
        return jsonify({"detail": "Ocurrió un error inesperado y no controlado en el servidor.", "code": "internal_error"}), 500


@purchase_order_item_bp.delete("/<id_po_item>")
def delete_po_item(id_po_item):
    session = None
    try:
        with get_session() as session:
            obj = session.get(PurchaseOrderItem, id_po_item)
            if not obj:
                return jsonify({"error": "PurchaseOrderItem not found"}), 404

            # Capture FK before delete — object loses its data after deletion
            order_id_for_calc = obj.ID_PurchaseOrder

            delete_with_retry(session, obj)

            # ── Recalculate Purchase.Total_spending + Job.Gqm_total_materials_fees ──
            # The deleted item is already gone from DB, so the sum naturally excludes it.
            _recalculate_purchase_total(order_id_for_calc, session)
            session.commit()
            # ────────────────────────────────────────────────────────────────────────

            return jsonify({"message": f"Deleted PurchaseOrderItem {id_po_item}"}), 200

    except IntegrityError as e:
        if session:
            session.rollback()
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": "Error de integridad: No se puede eliminar el purchase order item porque tiene registros relacionados."}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar purchase order item: {db_error}")
        return jsonify({"detail": "Error interno del servidor al interactuar con la base de datos.", "code": "db_error"}), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al eliminar purchase order item: {e}")
        return jsonify({"detail": "Ocurrió un error inesperado y no controlado en el servidor.", "code": "internal_error"}), 500