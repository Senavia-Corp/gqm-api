
from functools import wraps
from flask import request, jsonify, g
from src.utils.middleware.auth.jwt_handler import decode_access_token


def require_role(*allowed_roles):
    """
    allowed_roles = lista de roles permitidos para la ruta.
    Ej:
        @require_role("member")
        @require_role("member", "technician")
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):

            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return jsonify({"error": "Missing or invalid Authorization header"}), 401

            token = auth_header.split(" ")[1]
            payload = decode_access_token(token)

            if not payload:
                return jsonify({"error": "Invalid or expired token"}), 401

            user_role = payload.get("role")

            # Si se especificaron roles, validar acceso
            if allowed_roles and user_role not in allowed_roles:
                return jsonify({"error": "Forbidden: insufficient permissions"}), 403

            # Guardar info del usuario autenticado
            g.current_user = {
                "id": payload.get("sub"),
                "role": user_role
            }

            return f(*args, **kwargs)

        return wrapper
    return decorator
