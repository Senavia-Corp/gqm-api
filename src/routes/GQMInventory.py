# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.GQMInventoryModel import Inventory, InventoryCreate, InventoryUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger

# Blueprint de Inventory:
inventory_bp = Blueprint("inventory_blueprint", __name__,
                         url_prefix="/inventory")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todo el inventory
@inventory_bp.get("/")
@handle_exceptions()
@paginate()
def list_inventory():

    with get_session() as session:
        statement = (
            select(Inventory)
            .options(
                joinedload(Inventory.attachments),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        inventory_data = []

        for inventory in results:
            data = add_relationships(
                inventory, ["attachments"])
            inventory_data.append(data)

        return inventory_data, 200


# Ruta para conseguir un inventory por ID
@inventory_bp.get("/<id_inventory>")
@handle_exceptions()
def get_inventory(id_inventory):

    with get_session() as session:
        statement = (
            select(Inventory)
            .options(
                joinedload(Inventory.attachments),
            )
            .where(Inventory.ID_Inventory == id_inventory)
        )
        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Inventory not found.",
                               "inventory_not_found", 404)

        inventory_data = add_relationships(
            obj, ["attachments"])

        return jsonify(inventory_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un inventory
@inventory_bp.post("/")
@handle_exceptions()
def create_inventory():

    data = request.get_json()
    create_inventory = InventoryCreate.model_validate(data)
    obj = Inventory.model_validate(create_inventory)

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Inventory, "ID_Inventory", "INV")
        obj.ID_Inventory = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Inventory creado | inventory_id=%s",
            obj.ID_Inventory
        )

        return jsonify(obj.model_dump()), 201


# Ruta para actualizar un inventory
@inventory_bp.patch("/<id_inventory>")
@handle_exceptions()
def update_inventory(id_inventory):

    data = request.get_json()

    with get_session() as session:

        obj = session.get(Inventory, id_inventory)
        if not obj:
            raise AppException("Inventory not found.",
                               "inventory_not_found", 404)

        update_inventory = InventoryUpdate.model_validate(data)
        update_data_dict = update_inventory.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "🔄 Inventory actualizado | inventory_id=%s",
            obj.ID_Inventory
        )

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un inventory
@inventory_bp.delete("/<id_inventory>")
@handle_exceptions()
def delete_inventory(id_inventory):

    with get_session() as session:
        obj = session.get(Inventory, id_inventory)
        if not obj:
            raise AppException("Inventory not found.",
                               "inventory_not_found", 404)

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ Inventory eliminado | inventory_id=%s",
            id_inventory
        )

        return jsonify({
            "message": f"Inventory {id_inventory} eliminado correctamente"
        }), 200
