import os
import requests
from sqlmodel import select
import urllib.parse
from flask import Blueprint, redirect
from ...quickbooks.test_sandbox import get_company_info

from src.database.db_sqlmodel import get_session
from src.quickbooks.TokensModel import QuickBooksToken
from ...quickbooks.qbo_auth import get_qbo_basic_auth

qbo_bp = Blueprint("qbo_bp", __name__)


# Endpoint para conseguir info del sandbox
@qbo_bp.get("/test/company-info/<realm_id>")
def test_company_info(realm_id):
    data = get_company_info(realm_id)
    return data, 200


# Launch URL
@qbo_bp.get("/connect")
def connect_qbo():
    client_id = os.getenv("QBO_CLIENT_ID_DEV")  # Producción
    # Debe coincidir exactamente con lo registrado en Intuit
    redirect_uri = os.getenv("QBO_REDIRECT_URI_DEV")

    # URL de OAuth2 para producción
    base_url = "https://appcenter.intuit.com/connect/oauth2"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "state": "security_token"  # opcionalmente generar dinámico por sesión
    }

    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return redirect(url)


# Disconnect URL
@qbo_bp.get("/disconnect/<realm_id>")
def disconnect_qbo(realm_id):
    with get_session() as session:
        token_record = session.exec(
            select(QuickBooksToken).where(QuickBooksToken.realm_id == realm_id)
        ).first()

        if not token_record:
            return {"error": "No QuickBooks connection found"}, 404

        # Endpoint de revocación de tokens en producción
        url = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Basic {get_qbo_basic_auth()}"
        }

        payload = {
            "token": token_record.refresh_token
        }

        response = requests.post(url, json=payload, headers=headers)

        # Manejo seguro: Intuit a veces no devuelve JSON
        try:
            intuit_json = response.json()
        except:
            intuit_json = None

        # Eliminar registro de DB
        session.delete(token_record)
        session.commit()

        return {
            "message": "Disconnected from QuickBooks",
            "intuit_status": response.status_code,
            "intuit_response": intuit_json
        }, 200
