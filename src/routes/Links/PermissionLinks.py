from flask import Blueprint, jsonify
from ...database.db_sqlmodel import get_session
from ...models.PermissionModel import Permission
from ...models.RoleModel import Role
from ...models.MemberModel import Member
from ...models.TechnicianModel import Technician
from ...models.link_models.PermissionLinks import (
    PermissionRoleLink,
    PermissionMemberLink,
    PermissionTechLink
)

# ------------------- Link entre Permission y Role -------------------
permission_role_bp = Blueprint(
    "permission_role_blueprint", __name__, url_prefix="/permission_role")


# Vincular un permission con un role
@permission_role_bp.post("/permission/<permission_id>/role/<role_id>")
def assign_permission_to_role(permission_id, role_id):
    with get_session() as session:
        permission = session.get(Permission, permission_id)
        role = session.get(Role, role_id)

        if not permission or not role:
            return jsonify({"error": "Permission or Role not found"}), 404

        existing_link = session.get(
            PermissionRoleLink, (permission_id, role_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = PermissionRoleLink(
            permission_id=permission_id,
            role_id=role_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "permission_id": permission_id,
            "role_id": role_id
        }), 201


# Desvincular un permission de un role
@permission_role_bp.delete("/permission/<permission_id>/role/<role_id>")
def remove_permission_from_role(permission_id, role_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            PermissionRoleLink,
            (permission_id, role_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "permission_id": permission_id,
            "role_id": role_id
        }), 200


# ------------------- Link entre Permission y Member -------------------
permission_member_bp = Blueprint(
    "permission_member_blueprint", __name__, url_prefix="/permission_member")


# Vincular un permission con un member
@permission_member_bp.post("/permission/<permission_id>/member/<member_id>")
def assign_permission_to_member(permission_id, member_id):
    with get_session() as session:
        permission = session.get(Permission, permission_id)
        member = session.get(Member, member_id)

        if not permission or not member:
            return jsonify({"error": "Permission or Member not found"}), 404

        existing_link = session.get(
            PermissionMemberLink, (permission_id, member_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = PermissionMemberLink(
            permission_id=permission_id,
            member_id=member_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "permission_id": permission_id,
            "member_id": member_id
        }), 201


# Desvincular un permission de un member
@permission_member_bp.delete("/permission/<permission_id>/member/<member_id>")
def remove_permission_from_member(permission_id, member_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            PermissionMemberLink,
            (permission_id, member_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "permission_id": permission_id,
            "member_id": member_id
        }), 200


# ------------------- Link entre Permission y Technician -------------------
permission_tech_bp = Blueprint(
    "permission_tech_blueprint", __name__, url_prefix="/permission_tech")


# Vincular un permission con un tech
@permission_tech_bp.post("/permission/<permission_id>/tech/<tech_id>")
def assign_permission_to_tech(permission_id, tech_id):
    with get_session() as session:
        permission = session.get(Permission, permission_id)
        tech = session.get(Technician, tech_id)

        if not permission or not tech:
            return jsonify({"error": "Permission or Technician not found"}), 404

        existing_link = session.get(
            PermissionTechLink, (permission_id, tech_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = PermissionTechLink(
            permission_id=permission_id,
            tech_id=tech_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "permission_id": permission_id,
            "tech_id": tech_id
        }), 201


# Desvincular un permission de un tech
@permission_tech_bp.delete("/permission/<permission_id>/tech/<tech_id>")
def remove_permission_from_tech(permission_id, tech_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            PermissionTechLink,
            (permission_id, tech_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "permission_id": permission_id,
            "tech_id": tech_id
        }), 200
