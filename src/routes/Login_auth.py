from flask import Blueprint, request, jsonify
from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.auth.password_hashing import verify_password
from src.utils.middleware.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token
)
from src.models.MemberModel import Member
from src.models.TechnicianModel import Technician
from src.models.SubcontractorModel import Subcontractor
from src.models.RoleModel import Role
from src.utils.middleware.auth.routes_protection import get_user_context
from src.utils.policy_evaluator import PolicyEvaluator
from sqlalchemy.orm import joinedload

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# Ruta de inicio de sesión
@auth_bp.post("/login")
def login():
    data = request.get_json() or {}

    email = data.get("Email_Address")
    password = data.get("Password")

    if not email or not password:
        return jsonify({"error": "Email_Address and Password are required"}), 400

    with get_session() as session:

        # Buscar en Member
        stmt = select(Member).where(Member.Email_Address == email)
        member = session.exec(stmt).first()

        if member and verify_password(password, member.Password):
            user_type = "member"
            user_data = member.model_dump()
            user_data.pop("Password", None)
            user_id = member.ID_Member
            
            # Retrieve role details and associated permission policies
            policies = []
            role_detail = None
            if member.role:
                role_detail = {
                    "ID_Role": member.role.ID_Role,
                    "Name": member.role.Name
                }
                for perm in member.role.permissions:
                    if perm.Active and perm.Document:
                        policies.append(perm.Document)
            
            # Retrieve directly assigned permissions
            for perm in member.permissions:
                if perm.Active and perm.Document:
                    policies.append(perm.Document)
                    
            user_data["role_detail"] = role_detail
            user_data["policies"] = policies

        else:
            # Buscar en Technician
            stmt = select(Technician).where(Technician.Email_Address == email)
            technician = session.exec(stmt).first()

            if technician and verify_password(password, technician.Password):
                user_type = "technician"
                user_data = technician.model_dump()
                user_data.pop("Password", None)
                user_id = technician.ID_Technician
                
                # Technicians don't typically have roles, retrieve direct policies
                policies = []
                for perm in technician.permissions:
                    if perm.Active and perm.Document:
                        policies.append(perm.Document)
                        
                user_data["role_detail"] = None
                user_data["policies"] = policies
            else:
                # Buscar en Subcontractor
                stmt = select(Subcontractor).options(
                    joinedload(Subcontractor.role).joinedload(Role.permissions),
                    joinedload(Subcontractor.permissions)
                ).where(Subcontractor.Email_Address.contains(email))
                subcontractor = session.exec(stmt).unique().first()
                
                if subcontractor and subcontractor.Password and verify_password(password, subcontractor.Password):
                    user_type = "subcontractor"
                    user_data = subcontractor.model_dump()
                    user_data.pop("Password", None)
                    user_id = subcontractor.ID_Subcontractor
                    
                    policies = []
                    role_detail = None
                    if subcontractor.role:
                        role_detail = {
                            "ID_Role": subcontractor.role.ID_Role,
                            "Name": subcontractor.role.Name
                        }
                        for perm in subcontractor.role.permissions:
                            if perm.Active and perm.Document:
                                policies.append(perm.Document)

                    for perm in subcontractor.permissions:
                        if perm.Active and perm.Document:
                            policies.append(perm.Document)
                    
                    user_data["role_detail"] = role_detail
                    user_data["policies"] = policies
                else:
                    return jsonify({"error": "Invalid email or password"}), 401

        # Crear tokens
        access_token = create_access_token({
            "sub": user_id,
            "role": user_type
        })

        refresh_token = create_refresh_token({
            "sub": user_id,
            "role": user_type
        })

        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_type": user_type,
            "user_id": user_id,
            "user_data": user_data
        }), 200


# Para refrescar el token sin tener que iniciar sesión a cada hora
@auth_bp.post("/refresh")
def refresh():
    try:
        # 1. Obtener token desde JSON o Header
        json_data = request.get_json(silent=True) or {}
        token = json_data.get("refresh_token")

        if not token:
            # Intentar por Header
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

        if not token:
            return jsonify({"error": "Refresh token required"}), 400

        # 2. Decodificar refresh token
        payload = decode_refresh_token(token)

        if not payload:
            return jsonify({"error": "Invalid or expired refresh token"}), 401

        user_id = payload.get("sub")
        role = payload.get("role")

        if not user_id or not role:
            return jsonify({"error": "Malformed token"}), 400

        # 3. Validar que el usuario siga existiendo
        with get_session() as session:

            if role == "member":
                stmt = select(Member).where(Member.ID_Member == user_id)
                user = session.exec(stmt).first()

            elif role == "technician":
                stmt = select(Technician).where(
                    Technician.ID_Technician == user_id)
                user = session.exec(stmt).first()

            elif role == "subcontractor":
                stmt = select(Subcontractor).where(
                    Subcontractor.ID_Subcontractor == user_id)
                user = session.exec(stmt).first()

            else:
                return jsonify({"error": "Invalid role in token"}), 401

            if not user:
                return jsonify({"error": "User no longer exists"}), 404

            # REG-100: si el rol del usuario fue desactivado, no renovar
            user_role = getattr(user, "role", None)
            if user_role is not None and user_role.Active is False:
                return jsonify({"error": "User role deactivated"}), 401

        # 4. Crear nuevo access token
        new_access = create_access_token({
            "sub": user_id,
            "role": role
        })

        return jsonify({
            "access_token": new_access,
            "token_type": "bearer"
        }), 200

    except Exception as e:
        print(f"❌ Error en /refresh: {e}")
        return jsonify({"error": "Internal server error"}), 500


@auth_bp.get("/can")
def check_can():
    """
    Query: ?actions=action1,action2,...
    Returns: { "results": { "action1": true/false, ... } }
    If no valid token is present, all actions evaluate to false.
    Used by the frontend to know which UI elements to show/restrict.
    """
    actions_param = request.args.get("actions", "")
    if not actions_param:
        return jsonify({"results": {}}), 200

    actions_list = [a.strip() for a in actions_param.split(",") if a.strip()]
    _, _, policies = get_user_context()

    results = {action: PolicyEvaluator.evaluate(policies, action) for action in actions_list}
    return jsonify({"results": results}), 200
