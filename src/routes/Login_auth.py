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

        else:
            # Buscar en Technician
            stmt = select(Technician).where(Technician.Email_Address == email)
            technician = session.exec(stmt).first()

            if technician and verify_password(password, technician.Password):
                user_type = "technician"
                user_data = technician.model_dump()
                user_data.pop("Password", None)
                user_id = technician.ID_Technician
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

            else:
                return jsonify({"error": "Invalid role in token"}), 401

            if not user:
                return jsonify({"error": "User no longer exists"}), 404

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
