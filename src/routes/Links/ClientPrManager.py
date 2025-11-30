from flask import Blueprint, jsonify
from ...database.db_sqlmodel import get_session
from ...models.ClientModel import Client
from ...models.PropertyManagerModel import PropertyManager
from ...models.link_models.ClientPManager import ClientPrManagerLink


client_pr_manager_bp = Blueprint(
    "client_pr_manager_blueprint", __name__, url_prefix="/client_pr_manager")


# Vincular un cliente con un property manager
@client_pr_manager_bp.post("/client/<clients_id>/manager/<property_manager_id>")
def assign_client_to_manager(clients_id, property_manager_id):
    with get_session() as session:
        job = session.get(Client, clients_id)
        member = session.get(PropertyManager, property_manager_id)

        if not job or not member:
            return jsonify({"error": "Job or Property Manager not found"}), 404

        existing_link = session.get(
            ClientPrManagerLink, (clients_id, property_manager_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = ClientPrManagerLink(
            clients_id=clients_id,
            property_manager_id=property_manager_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "clients_id": clients_id,
            "property_manager_id": property_manager_id
        }), 201


# Desvincular un cliente de un property manager
@client_pr_manager_bp.delete("/client/<clients_id>/manager/<property_manager_id>")
def remove_client_from_manager(clients_id, property_manager_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            ClientPrManagerLink,
            (clients_id, property_manager_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "clients_id": clients_id,
            "property_manager_id": property_manager_id
        }), 200
