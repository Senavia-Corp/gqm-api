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


# ── Rate limit (REG-051/REG-086) ─────────────────────────────────────────
# Ventana fija por (IP, email), COMPARTIDA en la base de datos.
#
# Antes era un dict en memoria del proceso. En serverless eso no frena nada:
# cada peticion puede caer en otra instancia y ninguna acumula. Medido el
# 10-ago-2026 contra gqm-api-dev: 12 logins fallidos seguidos -> 12x 401, ni un
# 429. El mismo bucle en local (proceso unico) frenaba en el intento 21.
#
# Se usa la BD que ya hay en vez de meter Redis/Upstash: el volumen de logins es
# minusculo y asi no se añade infraestructura ni dependencias.
import logging as _logging
import time as _time
from datetime import datetime, timedelta, timezone

from decouple import config as _env
from sqlalchemy import delete as _sa_delete
from sqlalchemy import func as _sa_func
from sqlmodel import select as _sa_select

from src.models.LoginAttemptModel import LoginAttempt

_logger = _logging.getLogger(__name__)

_WINDOW_SECONDS = _env("LOGIN_RATE_WINDOW_SECONDS", default=60, cast=int)
_MAX_ATTEMPTS = _env("LOGIN_RATE_MAX_ATTEMPTS", default=5, cast=int)

# Respaldo en memoria: SOLO se usa si la BD falla al consultar la ventana. No es
# el camino normal, y si se usa el limite vuelve a ser por instancia.
_ATTEMPTS: dict = {}


def _rate_limited_memoria(key: str) -> bool:
    now = _time.time()
    hits = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW_SECONDS]
    if len(hits) >= _MAX_ATTEMPTS:
        _ATTEMPTS[key] = hits
        return True
    hits.append(now)
    _ATTEMPTS[key] = hits
    return False


def _rate_limited(key: str) -> bool:
    """True si `key` ya gasto su cupo en la ventana. Cuenta en la BD."""
    ahora = datetime.now(timezone.utc)
    corte = ahora - timedelta(seconds=_WINDOW_SECONDS)
    try:
        with get_session() as session:
            # Limpieza oportunista: las filas fuera de ventana no sirven a nadie.
            session.exec(_sa_delete(LoginAttempt).where(LoginAttempt.created_at < corte))

            usados = session.exec(
                _sa_select(_sa_func.count())
                .select_from(LoginAttempt)
                .where(LoginAttempt.attempt_key == key)
                .where(LoginAttempt.created_at >= corte)
            ).one()
            usados = usados[0] if isinstance(usados, tuple) else usados

            if usados >= _MAX_ATTEMPTS:
                session.commit()
                return True

            session.add(LoginAttempt(attempt_key=key, created_at=ahora))
            session.commit()
            return False
    except Exception as e:  # noqa: BLE001
        # Fail-open a proposito: si la BD no responde el login tampoco puede
        # funcionar (necesita consultar Member), asi que no tiene sentido dejar
        # a todo el mundo fuera por no poder contar intentos.
        _logger.warning(f"rate limit: fallo el conteo en BD, uso el respaldo en memoria ({e})")
        return _rate_limited_memoria(key)


def _client_key(email: str) -> str:
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    return f"{ip}|{(email or '').lower()}"


def _json_object():
    """Cuerpo JSON solo si es un objeto; None en cualquier otro caso.

    `request.get_json() or {}` solo cubre el body vacío. Un JSON *válido* que no
    sea objeto ("texto", [1,2], 42) pasaba el `or {}` y reventaba en el .get()
    siguiente con AttributeError → 500 sin autenticar en las tres rutas públicas
    de este blueprint. Verificado en las 9 combinaciones el 10-ago-2026.
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


# Ruta de inicio de sesión
@auth_bp.post("/login")
def login():
    data = _json_object()
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    email = data.get("Email_Address")
    password = data.get("Password")

    if not email or not password:
        return jsonify({"error": "Email_Address and Password are required"}), 400

    if _rate_limited(_client_key(email)):
        return jsonify({"error": "Too many attempts, try again in a minute"}), 429

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
                # REG-036/REG-050: igualdad exacta (case-insensitive), jamás
                # substring — .contains hacía LIKE y podía resolver a OTRO
                # subcontratista cuyo email contuviera el buscado.
                from sqlalchemy import func as sa_func
                stmt = select(Subcontractor).options(
                    joinedload(Subcontractor.role).joinedload(Role.permissions),
                    joinedload(Subcontractor.permissions)
                ).where(sa_func.lower(Subcontractor.Email_Address)
                        == (email or "").strip().lower())
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
        # Un body que no sea objeto NO invalida la petición: esta ruta también
        # acepta el token por cabecera, así que se ignora y se sigue por ahí.
        json_data = _json_object() or {}
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


# ── Forgot / Reset password (REG-047/REG-049) ────────────────────────────
# Token stateless firmado con SECRET_KEY (itsdangerous, 30 min). Lleva un
# fragmento del hash actual de la contraseña: al cambiarla, el token muere
# → un solo uso sin tabla nueva.

_USER_TABLES = {
    "member": (Member, "ID_Member"),
    "technician": (Technician, "ID_Technician"),
    "subcontractor": (Subcontractor, "ID_Subcontractor"),
}


def _reset_serializer():
    from decouple import config as env_config
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(env_config("SECRET_KEY"), salt="gqm-password-reset")


def _find_user_by_email(session, email: str):
    from sqlalchemy import func as sa_func
    normalized = (email or "").strip().lower()
    for user_type, (Model, _pk) in _USER_TABLES.items():
        user = session.exec(
            select(Model).where(sa_func.lower(Model.Email_Address) == normalized)
        ).first()
        if user:
            return user_type, user
    return None, None


@auth_bp.post("/forgot-password")
def forgot_password():
    data = _json_object()
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400
    email = data.get("Email_Address")
    if not email:
        return jsonify({"error": "Email_Address is required"}), 400

    if _rate_limited(_client_key(f"forgot|{email}")):
        return jsonify({"error": "Too many attempts, try again in a minute"}), 429

    with get_session() as session:
        user_type, user = _find_user_by_email(session, email)
        if user and user.Password:
            _pk_field = _USER_TABLES[user_type][1]
            token = _reset_serializer().dumps({
                "uid": getattr(user, _pk_field),
                "ut": user_type,
                "ph": user.Password[-12:],  # fragmento → un solo uso
            })
            from decouple import config as env_config
            panel = env_config("PANEL_BASE_URL", default="http://localhost:3100").rstrip("/")
            from src.services.email_service import send_password_reset
            send_password_reset(user.Email_Address, f"{panel}/reset-password?token={token}")

    # Siempre 200: no filtrar si el email existe
    return jsonify({"message": "If the email exists, a reset link was sent"}), 200


@auth_bp.post("/reset-password")
def reset_password():
    from itsdangerous import BadSignature, SignatureExpired

    data = _json_object()
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400
    token = data.get("token")
    new_password = data.get("Password")
    if not token or not new_password:
        return jsonify({"error": "token and Password are required"}), 400
    if len(new_password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    try:
        payload = _reset_serializer().loads(token, max_age=1800)
    except SignatureExpired:
        return jsonify({"error": "Reset link expired"}), 400
    except BadSignature:
        return jsonify({"error": "Invalid reset link"}), 400

    entry = _USER_TABLES.get(payload.get("ut"))
    if not entry:
        return jsonify({"error": "Invalid reset link"}), 400
    Model, pk_field = entry

    with get_session() as session:
        user = session.exec(
            select(Model).where(getattr(Model, pk_field) == payload.get("uid"))
        ).first()
        if not user or not user.Password or user.Password[-12:] != payload.get("ph"):
            # ya usado (el hash cambió) o usuario inexistente
            return jsonify({"error": "Invalid or already used reset link"}), 400

        from src.utils.middleware.auth.password_hashing import hash_password
        user.Password = hash_password(new_password)
        session.add(user)
        session.commit()

    return jsonify({"message": "Password updated"}), 200
