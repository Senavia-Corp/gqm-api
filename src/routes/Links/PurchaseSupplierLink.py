from flask import Blueprint, jsonify
from ...database.db_sqlmodel import get_session
from ...models.PurchaseModel import Purchase
from ...models.SupplierModel import Supplier
from ...models.link_models.PurchaseSupplier import PurchaseSupplierLink


# ------------------- Link entre Purchase y Supplier -------------------
purchase_supplier_bp = Blueprint(
    "purchase_supplier_blueprint", __name__, url_prefix="/purchase_supplier")


# Vincular una purchase con un supplier
@purchase_supplier_bp.post("/purchase/<purchase_id>/supplier/<supplier_id>")
def assign_purchase_to_supplier(purchase_id, supplier_id):
    with get_session() as session:
        purchase = session.get(Purchase, purchase_id)
        supplier = session.get(Supplier, supplier_id)

        if not purchase or not supplier:
            return jsonify({"error": "Purchase or Supplier not found"}), 404

        existing_link = session.get(
            PurchaseSupplierLink, (purchase_id, supplier_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = PurchaseSupplierLink(
            purchase_id=purchase_id,
            supplier_id=supplier_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "purchase_id": purchase_id,
            "supplier_id": supplier_id
        }), 201


# Desvincular una purchase de un supplier
@purchase_supplier_bp.delete("/purchase/<purchase_id>/supplier/<supplier_id>")
def remove_purchase_from_supplier(purchase_id, supplier_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            PurchaseSupplierLink,
            (purchase_id, supplier_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "purchase_id": purchase_id,
            "supplier_id": supplier_id
        }), 200
