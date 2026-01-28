from flask import Blueprint, jsonify, request
from ...database.db_sqlmodel import get_session
from ...models.ClientModel import Client
from ...models.ManagerModel import Manager
from ...models.MemberModel import Member
from ...models.link_models.ClientLinks import ClientMemberLink, ClientManagerLink

# ------------------- Link entre Client y Manager -------------------
client_manager_bp = Blueprint(
    "client_manager_blueprint", __name__, url_prefix="/client_manager")


# Vincular un cliente con un manager
@client_manager_bp.post("/client/<clients_id>/manager/<manager_id>")
def assign_client_to_manager(clients_id, manager_id):
    with get_session() as session:
        client = session.get(Client, clients_id)
        prmanager = session.get(Manager, manager_id)

        if not client or not prmanager:
            return jsonify({"error": "Client or Manager not found"}), 404

        existing_link = session.get(
            ClientManagerLink, (clients_id, manager_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = ClientManagerLink(
            clients_id=clients_id,
            manager_id=manager_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "clients_id": clients_id,
            "manager_id": manager_id
        }), 201


# Desvincular un cliente de un manager
@client_manager_bp.delete("/client/<clients_id>/manager/<manager_id>")
def remove_client_from_manager(clients_id, manager_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            ClientManagerLink,
            (clients_id, manager_id)  # Clave primaria compuesta
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
            "manager_id": manager_id
        }), 200


# ------------------- Link entre Client y Member -------------------
client_member_bp = Blueprint(
    "client_member_blueprint", __name__, url_prefix="/client_member")


# Vincular un cliente con un member
@client_member_bp.post("/client/<clients_id>/member/<members_id>")
def assign_client_to_member(clients_id, members_id):
    data = request.get_json(silent=True) or {}
    rol = data.get("rol")

    with get_session() as session:
        client = session.get(Client, clients_id)
        member = session.get(Member, members_id)

        if not client or not member:
            return jsonify({"error": "Client or Member not found"}), 404

        existing_link = session.get(
            ClientMemberLink, (clients_id, members_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = ClientMemberLink(
            clients_id=clients_id,
            members_id=members_id,
            rol=rol
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "clients_id": clients_id,
            "members_id": members_id,
            "rol": rol
        }), 201


# Actualizar el campo rol
@client_member_bp.patch("/client/<clients_id>/member/<members_id>/rol")
def update_role(clients_id, members_id):
    data = request.get_json(silent=True) or {}
    rol = data.get("rol")  # puede ser None

    with get_session() as session:
        link = session.get(
            ClientMemberLink, (clients_id, members_id)
        )

        if not link:
            return jsonify({"error": "Relationship not found"}), 404

        link.rol = rol
        session.commit()

        return jsonify({
            "status": "Role updated 🔁",
            "rol": rol
        }), 200


# Desvincular un cliente de un member
@client_member_bp.delete("/client/<clients_id>/member/<members_id>")
def remove_client_from_member(clients_id, members_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            ClientMemberLink,
            (clients_id, members_id)  # Clave primaria compuesta
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
            "members_id": members_id
        }), 200
