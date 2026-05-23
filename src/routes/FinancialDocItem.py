# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.FinancialDocItemModel import FinancialDoc_Item, FDItemCreate, FDItemUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.auth.routes_protection import require_permission
from ..utils.audit import audit
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException


# Blueprint de FinancialDoc_Item:
fdoc_item_bp = Blueprint("fdoc_item_blueprint",
                         __name__, url_prefix="/fdoc_item")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los FinancialDoc_Item
@fdoc_item_bp.get("/")
@require_permission("financial_doc_item:read")
@handle_exceptions()
@paginate()
def list_fditems():
    with get_session() as session:
        statement = (
            select(FinancialDoc_Item)
            .options(
                joinedload(FinancialDoc_Item.financial_document)
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        fditem_data = [
            add_relationships(
                fditem, ["financial_document"])
            for fditem in results
        ]

        return fditem_data, 200


# Ruta para conseguir un FinancialDoc_Item por ID
@fdoc_item_bp.get("/<id_fdocitem>")
@require_permission("financial_doc_item:read")
@handle_exceptions()
def get_fditem(id_fdocitem):
    with get_session() as session:
        statement = (
            select(FinancialDoc_Item)
            .options(
                joinedload(FinancialDoc_Item.financial_document)
            )
            .where(FinancialDoc_Item.ID_FDItem == id_fdocitem)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("FinancialDoc Item not found", "not_found", 404)

        fditem_data = add_relationships(
            obj, ["financial_document"])

        return jsonify(fditem_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un FinancialDoc_Item
@fdoc_item_bp.post("/")
@require_permission("financial_doc_item:create")
@handle_exceptions()
@audit("FinancialDoc Item created", entity_type="FinancialDoc_Item", id_from="response")
def create_fditem():
    data = request.get_json()
    create_fditem = FDItemCreate.model_validate(data)
    obj = FinancialDoc_Item.model_validate(create_fditem)

    with get_session() as session:
        new_id = generate_custom_id(
            session, FinancialDoc_Item, "ID_FDItem", "FDI")
        obj.ID_FDItem = new_id

        save_with_retry(session, obj)

        return jsonify(obj.model_dump()), 201


# Ruta para actualizar un FinancialDoc_Item
@fdoc_item_bp.patch("/<id_fdocitem>")
@require_permission("financial_doc_item:update")
@handle_exceptions()
@audit("FinancialDoc Item updated", entity_type="FinancialDoc_Item", id_param="id_fdocitem")
def update_fditem(id_fdocitem):
    data = request.get_json()
    with get_session() as session:
        obj = session.get(FinancialDoc_Item, id_fdocitem)
        if not obj:
            raise AppException("FinancialDoc Item not found", "not_found", 404)

        update_fditem = FDItemUpdate.model_validate(data)
        update_data_dict = update_fditem.model_dump(
            exclude_unset=True)

        for key, value in update_data_dict.items():
            setattr(obj, key, value)

        save_with_retry(session, obj)

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un FinancialDoc_Item
@fdoc_item_bp.delete("/<id_fdocitem>")
@require_permission("financial_doc_item:delete")
@handle_exceptions()
@audit("FinancialDoc Item deleted", entity_type="FinancialDoc_Item", id_param="id_fdocitem")
def delete_fditem(id_fdocitem):
    with get_session() as session:
        obj = session.get(FinancialDoc_Item, id_fdocitem)
        if not obj:
            raise AppException("FinancialDoc Item not found", "not_found", 404)

        delete_with_retry(session, obj)

        return jsonify({"message": f"Deleted FinancialDoc Item {id_fdocitem}"}), 200
