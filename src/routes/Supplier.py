# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.SupplierModel import Supplier, SupplierCreate, SupplierUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger

# Blueprint de Supplier:
supplier_bp = Blueprint("supplier_blueprint", __name__,
                        url_prefix="/supplier")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los proveedores
@supplier_bp.get("/")
@handle_exceptions()
@paginate()
def list_suppliers():

    with get_session() as session:
        statement = (
            select(Supplier)
            .options(
                joinedload(Supplier.attachments),
                joinedload(Supplier.purchases),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        suppliers_data = []

        for suppliers in results:
            data = add_relationships(
                suppliers, ["attachments", "purchases"])
            suppliers_data.append(data)

        return suppliers_data, 200


# Ruta para conseguir un distruibidor por ID
@supplier_bp.get("/<id_supplier>")
@handle_exceptions()
def get_supplier(id_supplier):

    with get_session() as session:
        statement = (
            select(Supplier)
            .options(
                joinedload(Supplier.attachments),
                joinedload(Supplier.purchases),
            )
            .where(Supplier.ID_Supplier == id_supplier)
        )
        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Supplier not found.",
                               "supplier_not_found", 404)

        suppliers_data = add_relationships(
            obj, ["attachments", "purchases"])

        return jsonify(suppliers_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un distruibidor
@supplier_bp.post("/")
@handle_exceptions()
def create_supplier():

    data = request.get_json()
    create_supplier = SupplierCreate.model_validate(data)
    obj = Supplier.model_validate(create_supplier)

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Supplier, "ID_Supplier", "SUP")
        obj.ID_Supplier = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Supplier creado | supplier_id=%s",
            obj.ID_Supplier
        )

        return jsonify(obj.model_dump()), 201


# Ruta para actualizar un proveedor
@supplier_bp.patch("/<id_supplier>")
@handle_exceptions()
def update_supplier(id_supplier):

    data = request.get_json()

    with get_session() as session:

        obj = session.get(Supplier, id_supplier)
        if not obj:
            raise AppException("Supplier not found.",
                               "supplier_not_found", 404)

        update_supplier = SupplierUpdate.model_validate(data)
        update_data_dict = update_supplier.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "🔄 Supplier actualizado | supplier_id=%s",
            obj.ID_Supplier
        )

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un proveedor
@supplier_bp.delete("/<id_supplier>")
@handle_exceptions()
def delete_supplier(id_supplier):

    with get_session() as session:
        obj = session.get(Supplier, id_supplier)
        if not obj:
            raise AppException("Supplier not found.",
                               "supplier_not_found", 404)

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ Supplier eliminado | supplier_id=%s",
            id_supplier
        )

        return jsonify({
            "message": f"Supplier {id_supplier} eliminado correctamente"
        }), 200
