from flask import Blueprint, request, session
import os
import base64
import requests
from datetime import datetime, timedelta
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.QBOTokensModel import QuickBooksToken
from src.utils.crypto import decrypt_token, encrypt_token


# Blueprint
qbo_oauth_bp = Blueprint("qbo_oauth_bp", __name__)


# 1. CALLBACK: obtiene el CODE y genera tokens
# ============================================
@qbo_oauth_bp.route("/callback")
def qbo_callback():
    code = request.args.get("code")
    realmId = request.args.get("realmId")
    state = request.args.get("state")

    # Validar state para prevenir CSRF (comparación en tiempo constante)
    import hmac
    expected_state = session.get("qbo_state")
    if not state or not expected_state or not hmac.compare_digest(state, expected_state):
        return "Invalid state parameter, possible CSRF attack", 400

    if not code or not realmId:
        return "Missing code or realmId", 400

    # Clear state after validation
    session.pop("qbo_state", None)

    tokens = exchange_code_for_tokens(code)

    # Guardar tokens en PostgreSQL (db_session: no sombrear la session de Flask)
    with get_session() as db_session:
        existing = db_session.exec(
            select(QuickBooksToken).where(QuickBooksToken.realm_id == realmId)
        ).first()

        if existing:
            existing.access_token = encrypt_token(tokens["access_token"])
            existing.refresh_token = encrypt_token(tokens["refresh_token"])
            existing.token_type = tokens.get("token_type")
            existing.expires_in = tokens["expires_in"]
            existing.refresh_token_expires_in = tokens.get(
                "x_refresh_token_expires_in")
            existing.updated_at = datetime.now()
        else:
            new_entry = QuickBooksToken(
                realm_id=realmId,
                access_token=encrypt_token(tokens["access_token"]),
                refresh_token=encrypt_token(tokens["refresh_token"]),
                token_type=tokens.get("token_type"),
                expires_in=tokens["expires_in"],
                refresh_token_expires_in=tokens.get(
                    "x_refresh_token_expires_in")
            )
            db_session.add(new_entry)

        db_session.commit()

    return "QuickBooks Connected Successfully", 200


# 2. INTERCAMBIO INICIAL: code → tokens
# =======================================
def exchange_code_for_tokens(code):
    client_id = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")
    redirect_uri = os.getenv("QBO_REDIRECT_URI")

    auth_header = base64.b64encode(
        f"{client_id}:{client_secret}".encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri
    }

    url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    response = requests.post(url, headers=headers, data=data)

    # Jamás loguear el cuerpo: contiene access/refresh tokens en claro
    print("QBO token exchange STATUS:", response.status_code)

    return response.json()


# 3. REFRESH: obtiene nuevos tokens
# =========================================
def refresh_access_token(refresh_token):
    client_id = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")

    auth_header = base64.b64encode(
        f"{client_id}:{client_secret}".encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    response = requests.post(url, headers=headers, data=data)

    return response.json()


# 4. FUNCIÓN CENTRAL: obtener token válido SIEMPRE
# ===================================================
def get_valid_access_token(realm_id):
    with get_session() as session:
        token_record = session.exec(
            select(QuickBooksToken)
            .where(QuickBooksToken.realm_id == realm_id)).first()

        if not token_record:
            raise Exception("QuickBooks not connected for this company.")

        # Calcular expiración
        expires_at = token_record.updated_at + \
            timedelta(seconds=token_record.expires_in)
        buffer_time = timedelta(minutes=5)

        # Si NO expiró → se devuelve el token
        if datetime.now() < (expires_at - buffer_time):
            return decrypt_token(token_record.access_token)

        # Si expiró → se genera uno nuevo
        print(f"Refrescando token para realm: {realm_id}...")
        new_tokens = refresh_access_token(decrypt_token(token_record.refresh_token))

        # Validación de respuesta exitosa antes de guardar
        if "error" in new_tokens:
            # Si el refresh_token falló (ej. fue invalidado manualmente), se re-autoriza
            raise Exception(
                f"Error de Intuit: {new_tokens.get('error_description')}")

        # Guardamos nuevos tokens
        token_record.access_token = encrypt_token(new_tokens["access_token"])
        token_record.refresh_token = encrypt_token(new_tokens["refresh_token"])
        token_record.expires_in = new_tokens["expires_in"]
        token_record.refresh_token_expires_in = new_tokens.get(
            "x_refresh_token_expires_in", token_record.refresh_token_expires_in)
        token_record.updated_at = datetime.now()

        session.add(token_record)
        session.commit()
        session.refresh(token_record)

        return decrypt_token(token_record.access_token)


# Helper que construye la cabecera Basic Authorization requerida por Intuit
def get_qbo_basic_auth() -> str:

    # Retorna la cadena base64 necesaria para la cabecera Authorization: Basic <value>

    client_id = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "QBO_CLIENT_ID and QBO_CLIENT_SECRET must be set in environment variables")

    raw = f"{client_id}:{client_secret}"
    return base64.b64encode(raw.encode()).decode()
