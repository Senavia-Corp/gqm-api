from flask import Blueprint, jsonify, request
from ...database.db_sqlmodel import get_session
from ...models.ClientModel import Client
from ...models.ManagerModel import Manager
from ...models.MemberModel import Member
from ...models.link_models.ClientLinks import ClientMemberLink, ClientManagerLink
from ...podio.services.client_services import podio_clients_router
from src.utils.mappers.convert_value_podio import convert_value_for_podio
from src.utils.mappers.mapper_aux_functions import register_event
from src.utils.audit import log_activity, SOURCE_APP


# ------------------- Link entre Client y Manager -------------------
client_manager_bp = Blueprint(
    "client_manager_blueprint", __name__, url_prefix="/client_manager")


# Vincular un cliente con un manager
@client_manager_bp.post("/client/<clients_id>/manager/<manager_id>")
def assign_client_to_manager(clients_id, manager_id):
    data = request.get_json(silent=True) or {}
    rol = data.get("rol")
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    member_id_header = request.headers.get("X-User-Id") or None

    with get_session() as session:

        client = session.get(Client, clients_id)
        manager = session.get(Manager, manager_id)

        if not client or not manager:
            return jsonify({"error": "Client or Manager not found"}), 404

        existing_link = session.get(
            ClientManagerLink, (clients_id, manager_id))

        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        # ----------- 🔵 CREAR EN DB
        link = ClientManagerLink(
            clients_id=clients_id,
            manager_id=manager_id,
            rol=rol
        )

        session.add(link)

        # ----------- 🟢 CREAR EN PODIO (🔄 Enviar PATCH)
        if sync_podio:
            if client.podio_item_id and manager.Manager_name:

                podio_service = podio_clients_router.get_service()
                podio_fields = {}

                if link.rol == "Prop. Manager":
                    podio_fields["contact-name"] = convert_value_for_podio(
                        manager.Manager_name, "text"
                    )

                elif link.rol == "Regional Manager":
                    podio_fields["regional-manager"] = convert_value_for_podio(
                        manager.Manager_name, "text"
                    )

                if podio_fields:
                    podio_service.update_item(
                        int(client.podio_item_id), podio_fields)

                # Anti-loop: registrar evento
                register_event(client.podio_item_id)

        log_activity(
            session,
            action="Manager linked to Client",
            entity_id=clients_id,
            entity_type="Client",
            member_id=member_id_header,
            description=f"Manager: {manager.Manager_name or manager_id} | Role: {rol}",
            source=SOURCE_APP
        )

        session.commit()
        return jsonify({
            "status": "Linked 🔗",
            "clients_id": clients_id,
            "manager_id": manager_id,
            "rol": rol
        }), 201


# Actualizar el campo rol
@client_manager_bp.patch("/client/<clients_id>/manager/<manager_id>/rol")
def update_role(clients_id, manager_id):
    data = request.get_json(silent=True) or {}
    rol = data.get("rol")  # puede ser None
    member_id_header = request.headers.get("X-User-Id") or None

    with get_session() as session:
        link = session.get(
            ClientManagerLink, (clients_id, manager_id)
        )

        if not link:
            return jsonify({"error": "Relationship not found"}), 404

        link.rol = rol

        log_activity(
            session,
            action="Rol of manager updated",
            entity_id=clients_id,
            entity_type="Client",
            member_id=member_id_header,
            description=f"Manager: {manager_id} | Role: {rol}",
            source=SOURCE_APP
        )

        session.commit()

        return jsonify({
            "status": "Role updated 🔁",
            "rol": rol
        }), 200


# Desvincular un cliente de un manager
@client_manager_bp.delete("/client/<clients_id>/manager/<manager_id>")
def remove_client_from_manager(clients_id, manager_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    member_id_header = request.headers.get("X-User-Id") or None

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

        # Buscamos client, manager y rol antes de borrar
        client = session.get(Client, clients_id)
        manager = session.get(Manager, manager_id)
        rol_to_update = link.rol

        # ----------- 🟢 DELETE EN PODIO (🔄 Enviar PATCH)
        if sync_podio:
            if client and client.podio_item_id and rol_to_update:
                podio_service = podio_clients_router.get_service()

                if rol_to_update == "Prop. Manager":
                    field_name = "contact-name"
                elif rol_to_update == "Regional Manager":
                    field_name = "regional-manager"
                else:
                    field_name = None

                if field_name:
                    podio_service.update_item(
                        int(client.podio_item_id),
                        {field_name: []}  # limpiar campo en podio
                    )

                    register_event(client.podio_item_id)

        # ----------- 🔴 BORRAR EN DB
        session.delete(link)

        log_activity(
            session,
            action="Manager unlinked from Client",
            entity_id=clients_id,
            entity_type="Client",
            member_id=member_id_header,
            description=f"Manager: {manager.Manager_name if manager else manager_id}",
            source=SOURCE_APP
        )

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
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    member_id_header = request.headers.get("X-User-Id") or None

    with get_session() as session:
        client = session.get(Client, clients_id)
        member = session.get(Member, members_id)

        if not client or not member:
            return jsonify({"error": "Client or Member not found"}), 404

        existing_link = session.get(
            ClientMemberLink, (clients_id, members_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        # ----------- 🔵 CREAR EN DB
        link = ClientMemberLink(
            clients_id=clients_id,
            members_id=members_id,
            rol=rol
        )

        session.add(link)

        # ----------- 🟢 CREAR EN PODIO (🔄 Enviar PATCH)
        if sync_podio:
            if client.podio_item_id and member.podio_profile_id:

                podio_service = podio_clients_router.get_service()
                podio_fields = {}

                if link.rol == "Acc. Rep":
                    podio_fields["acc-rep"] = convert_value_for_podio(
                        member.podio_profile_id, "contact"
                    )

                elif link.rol == "Inv/Acc Pro":
                    podio_fields["invacc-pro"] = convert_value_for_podio(
                        member.podio_profile_id, "contact"
                    )

                if podio_fields:
                    podio_service.update_item(
                        int(client.podio_item_id), podio_fields)

                # Anti-loop: registrar evento
                register_event(client.podio_item_id)

        log_activity(
            session,
            action="Member linked to Client",
            entity_id=clients_id,
            entity_type="Client",
            member_id=member_id_header,
            description=f"Member: {member.Member_Name or members_id} | Role: {rol}",
            source=SOURCE_APP
        )

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
    member_id_header = request.headers.get("X-User-Id") or None

    with get_session() as session:
        link = session.get(
            ClientMemberLink, (clients_id, members_id)
        )

        if not link:
            return jsonify({"error": "Relationship not found"}), 404

        link.rol = rol

        log_activity(
            session,
            action="Rol of member updated",
            entity_id=clients_id,
            entity_type="Client",
            member_id=member_id_header,
            description=f"Member: {members_id} | Role: {rol}",
            source=SOURCE_APP
        )

        session.commit()

        return jsonify({
            "status": "Role updated 🔁",
            "rol": rol
        }), 200


# Desvincular un cliente de un member
@client_member_bp.delete("/client/<clients_id>/member/<members_id>")
def remove_client_from_member(clients_id, members_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    member_id_header = request.headers.get("X-User-Id") or None

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

        # Buscamos client, member y rol antes de borrar
        client = session.get(Client, clients_id)
        member = session.get(Member, members_id)
        rol_to_update = link.rol

        # ----------- 🟢 DELETE EN PODIO (🔄 Enviar PATCH)
        if sync_podio:
            if client and client.podio_item_id and rol_to_update:
                podio_service = podio_clients_router.get_service()

                if rol_to_update == "Acc. Rep":
                    field_name = "acc-rep"
                elif rol_to_update == "Inv/Acc Pro":
                    field_name = "invacc-pro"
                else:
                    field_name = None

                if field_name:
                    podio_service.update_item(
                        int(client.podio_item_id),
                        {field_name: []}  # limpiar campo en podio
                    )

                    register_event(client.podio_item_id)

        # ----------- 🔴 BORRAR EN DB
        session.delete(link)

        log_activity(
            session,
            action="Member unlinked from Client",
            entity_id=clients_id,
            entity_type="Client",
            member_id=member_id_header,
            description=f"Member: {member.Member_Name if member else members_id}",
            source=SOURCE_APP
        )

        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "clients_id": clients_id,
            "members_id": members_id
        }), 200
