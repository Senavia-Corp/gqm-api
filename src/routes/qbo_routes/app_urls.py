import os
import requests
from sqlmodel import select
import urllib.parse
from flask import Blueprint, redirect
from ...tests.test_sandbox import get_company_info
from ...quickbooks.services.invoices_services import get_invoices, get_invoices_by_job
from ...quickbooks.services.payments_services import get_money_received
from ...quickbooks.services.bills_services import get_bills, get_bill_payments
from ...quickbooks.services.vendors_services import get_vendors

from src.database.db_sqlmodel import get_session
from src.quickbooks.TokensModel import QuickBooksToken
from ...quickbooks.qbo_auth import get_qbo_basic_auth

qbo_bp = Blueprint("qbo_bp", __name__, url_prefix="/qbo")


# Endpoint para conseguir info del sandbox ===> TEST
@qbo_bp.get("/test/company-info/<realm_id>")
def test_company_info(realm_id):
    data = get_company_info(realm_id)
    return data, 200


# Launch URL
@qbo_bp.get("/connect")
def connect_qbo():
    client_id = os.getenv("QBO_CLIENT_ID")  # Producción
    # Debe coincidir exactamente con lo registrado en Intuit
    redirect_uri = os.getenv("QBO_REDIRECT_URI")

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


# Endpoint para conseguir info de invoices reales
@qbo_bp.get("/invoices/<realm_id>")
def fetch_invoices(realm_id):
    data = get_invoices(realm_id)
    return data, 200


# Endpoint para conseguir invoices por Job (QIDxxxx)
@qbo_bp.get("/invoices/<realm_id>/job/<job_code>")
def fetch_invoices_by_job(realm_id, job_code):
    data = get_invoices_by_job(
        realm_id=realm_id,
        job_code=job_code
    )
    return data, 200


# Endpoint para conseguir info de payments reales
@qbo_bp.get("/money_received/<realm_id>")
def fetch_payments(realm_id):
    data = get_money_received(realm_id)
    return data, 200


# Endpoint para conseguir info de vendors reales
@qbo_bp.get("/vendors/<realm_id>")
def fetch_vendors(realm_id):
    data = get_vendors(realm_id)
    return data, 200


# Endpoint para conseguir info de bills reales
@qbo_bp.get("/bills/<realm_id>")
def fetch_bills(realm_id):
    data = get_bills(realm_id)
    return data, 200


# Endpoint para conseguir info de bill payments reales
@qbo_bp.get("/bill_payments/<realm_id>")
def fetch_bill_payments(realm_id):
    data = get_bill_payments(realm_id)
    return data, 200
