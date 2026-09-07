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

from ..utils.password_policy import validar_password, PasswordDebil  # noqa: E402

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


# Los espacios que quita `str.strip()` de Python. Se nombran porque `btrim()`
# de Postgres, SIN segundo argumento, quita SOLO el espacio: medido en este
# mismo Postgres, `btrim(E'ana@x.com\t')` devuelve `'ana@x.com\t'`. Sin esto la
# aplicacion y el indice unico de la migracion e9c1correo normalizan DISTINTO, y
# un correo con un tabulador final es el mismo usuario para una y otra clave
# para el otro: el duplicado se cuela. Es la clase de fallo de O-04 otra vez.
ESPACIOS = " \t\n\r\v\f"


def correo_normalizado(valor) -> str:
    """El correo tal y como se compara en TODAS partes."""
    return (valor or "").strip(ESPACIOS).lower()


def columna_correo_normalizada(columna):
    """La misma normalizacion, en SQL. Igual que el indice de e9c1correo."""
    from sqlalchemy import func as sa_func
    return sa_func.lower(sa_func.btrim(columna, ESPACIOS))


def _client_key(email: str, *, ambito: str = "") -> str:
    """Clave del limitador. `ambito` va DESPUES de normalizar, nunca antes.

    O-05 bis: la llamada de forgot-password era `_client_key(f"forgot|{email}")`,
    asi que el `.strip()` de aqui recortaba los extremos de
    `"forgot| ana@x.com"` —que no tiene ninguno— y el espacio interior
    sobrevivia. Medido:

        _client_key("forgot|ana@x.com")  -> 1.2.3.4|forgot|ana@x.com
        _client_key("forgot| ana@x.com") -> 1.2.3.4|forgot| ana@x.com

    Dos cupos distintos para el mismo usuario: bastaba anadir un espacio para
    reiniciar el limitador. El login, que pasaba el correo suelto, si estaba
    bien. Con el ambito como parametro el correo se normaliza SIEMPRE.
    """
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    return f"{ip}|{ambito}{correo_normalizado(email)}"


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

    from sqlalchemy import func as sa_func

    if _rate_limited(_client_key(email)):
        return jsonify({"error": "Too many attempts, try again in a minute"}), 429

    with get_session() as session:

        # O-04 (auditoria de portal): la busqueda del correo era INCONSISTENTE
        # entre los tres tipos de principal. El subcontratista se buscaba con
        # lower() (REG-036/REG-050) y Member y Technician con igualdad exacta,
        # asi que un sub entraba escribiendo SUB-DEV@... y un tecnico con
        # TECH-DEV@... recibia 401 — indistinguible de una contrasena mal
        # escrita. Con 432 altas importadas de Podio, donde la capitalizacion
        # del correo no la controla nadie, eso es un fallo de acceso silencioso.
        # Se normaliza igual en los tres. Mismo criterio que ya afirmaba
        # tests/integration/test_sub_login_exact_match.py: igualdad exacta,
        # insensible a mayusculas, jamas substring.
        correo = correo_normalizado(email)

        # Buscar en Member
        stmt = select(Member).where(
            columna_correo_normalizada(Member.Email_Address) == correo)
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
            stmt = select(Technician).where(
                columna_correo_normalizada(Technician.Email_Address) == correo)
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
                stmt = select(Subcontractor).options(
                    joinedload(Subcontractor.role).joinedload(Role.permissions),
                    joinedload(Subcontractor.permissions)
                ).where(columna_correo_normalizada(Subcontractor.Email_Address)
                        == correo)
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


# ── Sesión vigente (REG-038/REG-107) ─────────────────────────────────────
# El panel escribía rol y políticas en localStorage SOLO durante el login y no
# volvía a sincronizarlos nunca: un Full Admin que no cerrara sesión seguía con
# la etiqueta y los permisos del día que entró, y un cambio de rol no surtía
# efecto jamás. /refresh no servía para arreglarlo porque solo devuelve el
# access_token. Esta ruta expone el estado actual del usuario del JWT, con la
# misma forma que `user_data` en /login para que el cliente no tenga dos mapeos.
@auth_bp.get("/me")
def me():
    try:
        user_id, user_type, policies = get_user_context()
        if not user_id or not user_type:
            return jsonify({"error": "Not authenticated"}), 401

        with get_session() as session:
            user_data = None
            role_detail = None

            if user_type == "member":
                user = session.exec(
                    select(Member)
                    .options(joinedload(Member.role))
                    .where(Member.ID_Member == user_id)
                ).unique().first()
                if user:
                    user_data = user.model_dump()
                    if user.role:
                        role_detail = {
                            "ID_Role": user.role.ID_Role,
                            "Name": user.role.Name
                        }

            elif user_type == "technician":
                user = session.exec(
                    select(Technician).where(Technician.ID_Technician == user_id)
                ).first()
                if user:
                    user_data = user.model_dump()

            elif user_type == "subcontractor":
                user = session.exec(
                    select(Subcontractor)
                    .options(joinedload(Subcontractor.role))
                    .where(Subcontractor.ID_Subcontractor == user_id)
                ).unique().first()
                if user:
                    user_data = user.model_dump()
                    if user.role:
                        role_detail = {
                            "ID_Role": user.role.ID_Role,
                            "Name": user.role.Name
                        }

            else:
                return jsonify({"error": "Invalid role in token"}), 401

            if user_data is None:
                return jsonify({"error": "User no longer exists"}), 404

            user_data.pop("Password", None)

            # F-06: /me arma `user_data` con model_dump() directo, asi que NO
            # pasa por add_relationships y la redaccion central de
            # src/utils/portal_redaction.py no lo alcanza. Los identificadores
            # internos de la integracion con Podio no le sirven de nada a un rol
            # de portal y no deben salir; se quitan aqui para que /me diga lo
            # mismo que el resto de rutas y no haya una puerta de atras.
            if user_type in ("subcontractor", "technician"):
                for interno in ("podio_item_id", "podio_profile_id"):
                    user_data.pop(interno, None)

            user_data["role_detail"] = role_detail
            user_data["policies"] = policies

            return jsonify({
                "user_type": user_type,
                "user_id": user_id,
                "user_data": user_data
            }), 200

    except Exception as e:
        print(f"❌ Error en /me: {e}")
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


def _find_users_by_email(session, email: str):
    """TODOS los principales con ese correo, no el primero.

    O-05 (auditoria de portal): esto devolvia el PRIMER acierto por orden de
    tabla —member, technician, subcontractor— y con eso decidia a quien mandar
    el enlace. Pero `/auth/login` NO funciona asi: prueba la contrasena en las
    tres tablas y sigue buscando si no casa, de modo que un tecnico y un member
    que comparten correo entran los dos. Medido: los dos logins dan 200 con su
    user_type correcto, y forgot-password resolvia siempre al member.

    Consecuencia: el tecnico no podia recuperar su contrasena JAMAS, y como la
    respuesta es un 200 constante («if the email exists...») no habia forma de
    notarlo ni desde fuera ni desde dentro.

    El choque entre tablas es posible hoy: los indices unicos de la migracion
    e9c1correo son por tabla, no entre tablas — y en produccion hay 432
    subcontratistas importados de Podio junto a members y technicians, sin
    nadie que garantice que un correo no aparece en dos sitios.

    Se devuelven todos, en orden estable, para que la puerta de recuperacion
    tenga el mismo alcance que la de entrada.
    """
    normalizado = correo_normalizado(email)
    if not normalizado:
        return []
    encontrados = []
    for user_type, (Model, _pk) in _USER_TABLES.items():
        # Se normaliza la COLUMNA, no solo la entrada. Sin esto, una fila
        # guardada como 'ana@x.com ' —que la propia migracion e9c1correo
        # advierte que aparece en una importacion de 432 filas de Podio— es una
        # cuenta muda: existe, tiene contrasena, y ni entra ni se recupera.
        for user in session.exec(
            select(Model).where(
                columna_correo_normalizada(Model.Email_Address) == normalizado)
        ).all():
            encontrados.append((user_type, user))
    return encontrados


@auth_bp.post("/forgot-password")
def forgot_password():
    data = _json_object()
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400
    email = data.get("Email_Address")
    if not email:
        return jsonify({"error": "Email_Address is required"}), 400

    # `ambito` como parametro, no concatenado: ver `_client_key`. Concatenarlo
    # antes dejaba " ana@x.com" en un cupo propio y el limitador se reiniciaba
    # con solo anadir un espacio.
    if _rate_limited(_client_key(email, ambito="forgot|")):
        return jsonify({"error": "Too many attempts, try again in a minute"}), 429

    from decouple import config as env_config
    panel = env_config("PANEL_BASE_URL", default="http://localhost:3100").rstrip("/")

    destino = None
    enlaces = []
    with get_session() as session:
        for user_type, user in _find_users_by_email(session, email):
            if not user.Password:
                continue
            _pk_field = _USER_TABLES[user_type][1]
            token = _reset_serializer().dumps({
                "uid": getattr(user, _pk_field),
                "ut": user_type,
                "ph": user.Password[-12:],  # fragmento → un solo uso
            })
            destino = destino or user.Email_Address
            enlaces.append((user_type, f"{panel}/reset-password?token={token}"))

    # UN SOLO correo con todos los enlaces, y FUERA de la sesion de BD.
    #
    # Mandar uno por principal costaba hasta tres conexiones SMTP sincronas
    # dentro del `with get_session()`, con 15 s de timeout cada una, en una
    # funcion serverless sin `maxDuration`: si se cortaba a la mitad, el member
    # recibia su enlace y el tecnico y la subcontrata no — los dos roles que
    # esta auditoria va a encender.
    #
    # Y el tiempo de respuesta separaba sin solape 0, 1 y 3 principales
    # (~30 ms y ~110 ms), asi que el «siempre 200» no ocultaba nada al reloj:
    # el endpoint enumeraba quien esta dado de alta. Con un solo envio, el
    # tiempo deja de escalar con el numero de cuentas.
    if enlaces:
        try:
            from src.services.email_service import send_password_reset
            send_password_reset(destino, enlaces)
        except Exception:
            # Nunca cambia la respuesta. Sin este try, un fallo de SMTP
            # convertia el 200 constante en un 500 que solo aparecia cuando el
            # correo EXISTE: enumeracion directa, sin cronometro y sin
            # ambiguedad, justo lo contrario de lo que promete el 200 de abajo.
            _logger.exception("forgot-password: fallo el envio del correo de reinicio")

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
    # O-01: aqui solo se miraba `len < 8`, asi que "12345678" —que ESTA en la
    # lista de prohibidas— entraba y se escribia tal cual. Era la tercera puerta
    # para fijar una contrasena, y la unica que no exige estar autenticado: la
    # mas facil de usar y la que menos se mira.
    try:
        validar_password(new_password)
    except PasswordDebil as debil:
        return jsonify({"error": str(debil)}), 400

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
