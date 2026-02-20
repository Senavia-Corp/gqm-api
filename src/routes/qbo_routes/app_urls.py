import os
import requests
from sqlmodel import select
from flask import request
import urllib.parse
from flask import Blueprint, redirect
from ...tests.test_sandbox import get_company_info
from ...quickbooks.services.invoices_services import get_invoices, get_invoices_by_job
from ...quickbooks.services.payments_services import get_money_received, get_bill_payments
from ...quickbooks.services.bills_services import get_bills, get_bill_by_job
from ...quickbooks.services.vendors_services import get_vendors
from ...quickbooks.sync.sync_invoices_with_payments import sync_qbo_invoices_and_payments_by_job
from ...quickbooks.sync.sync_bills_with_payments import sync_qbo_bills_and_payments_by_job
from ...quickbooks.sync.sync_job_financials import sync_job_financials

from src.database.db_sqlmodel import get_session
from src.models.QBOTokensModel import QuickBooksToken
from ...quickbooks.qbo_auth import get_qbo_basic_auth

qbo_bp = Blueprint("qbo_bp", __name__, url_prefix="/qbo")


# Endpoint para conseguir info del sandbox ===> TEST
@qbo_bp.get("/test/company-info/<realm_id>")
def test_company_info(realm_id):
    data = get_company_info(realm_id)
    return data, 200


# ----------------------------------------------- #
# ----------- CONFIGURACIÓN DE LA APP ----------- #
# ----------------------------------------------- #
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


# ----------------------------------------------- #
# ----------- ENDPOINTS PARA INVOICES ----------- #
# ----------------------------------------------- #

# Endpoint para conseguir info de invoices reales
@qbo_bp.get("/invoices/<realm_id>")
def fetch_invoices(realm_id):

    start = int(request.args.get("start", 1))
    limit = int(request.args.get("limit", 100))

    data = get_invoices(
        realm_id=realm_id,
        start=start,
        limit=limit)
    return data, 200


# Endpoint para conseguir invoices por Job (QIDxxxx)
@qbo_bp.get("/invoices/<realm_id>/job/<job_code>")
def fetch_invoices_by_job(realm_id, job_code):

    start = int(request.args.get("start", 1))
    limit = int(request.args.get("limit", 100))

    data = get_invoices_by_job(
        realm_id=realm_id,
        job_code=job_code,
        start=start,
        limit=limit
    )
    return data, 200


# Endpoint para conseguir info de invoice payments
@qbo_bp.get("/money_received/<realm_id>")
def fetch_payments(realm_id):

    start = int(request.args.get("start", 1))
    limit = int(request.args.get("limit", 100))

    data = get_money_received(
        realm_id=realm_id,
        start=start,
        limit=limit
    )
    return data, 200


# ---------------- INVOICES + PAYMENTS ---------------- #

# Endpoint para sincronizar invoices + payments por Job
@qbo_bp.post("/invoices_payments/<realm_id>/job/<job_code>/sync")
def sync_inv_and_payments_by_job_endpoint(realm_id, job_code):

    try:
        start = int(request.args.get("start", 1))
        limit = int(request.args.get("limit", 100))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

    except ValueError:
        return {"error": "Invalid query parameters"}, 400

    result = sync_qbo_invoices_and_payments_by_job(
        realm_id=realm_id,
        job_code=job_code,
        start=start,
        limit=limit,
        dry_run=dry_run
    )

    return result, 200


# ----------------------------------------------- #
# ------------- ENDPOINTS PARA BILLS ------------ #
# ----------------------------------------------- #

# Endpoint para conseguir info de bills
@qbo_bp.get("/bills/<realm_id>")
def fetch_bills(realm_id):

    start = int(request.args.get("start", 1))
    limit = int(request.args.get("limit", 100))

    data = get_bills(
        realm_id=realm_id,
        start=start,
        limit=limit
    )
    return data, 200


# Endpoint para conseguir bills por Job (QIDxxxx)
@qbo_bp.get("/bills/<realm_id>/job/<job_code>")
def fetch_bills_by_job(realm_id, job_code):

    start = int(request.args.get("start", 1))
    limit = int(request.args.get("limit", 100))

    data = get_bill_by_job(
        realm_id=realm_id,
        job_code=job_code,
        start=start,
        limit=limit
    )
    return data, 200


# Endpoint para conseguir info de bill payments
@qbo_bp.get("/bill_payments/<realm_id>")
def fetch_bill_payments(realm_id):

    start = int(request.args.get("start", 1))
    limit = int(request.args.get("limit", 100))

    data = get_bill_payments(
        realm_id=realm_id,
        start=start,
        limit=limit
    )
    return data, 200


# ------------------ BILLS + PAYMENTS ----------------- #

# Endpoint para sincronizar bills + payments por Job
@qbo_bp.post("/bills_payments/<realm_id>/job/<job_code>/sync")
def sync_bill_and_bpayments_by_job_endpoint(realm_id, job_code):

    try:
        start = int(request.args.get("start", 1))
        limit = int(request.args.get("limit", 100))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

    except ValueError:
        return {"error": "Invalid query parameters"}, 400

    result = sync_qbo_bills_and_payments_by_job(
        realm_id=realm_id,
        job_code=job_code,
        start=start,
        limit=limit,
        dry_run=dry_run
    )

    return result, 200


# --------------------------------------------------- #
# ------------- ENDPOINT DE SYNC POR JOB ------------ #
# --------------------------------------------------- #
@qbo_bp.post("/sync-full-job/<realm_id>/<job_code>")
def sync_full_job_endpoint(realm_id, job_code):
    """
    Endpoint maestro para sincronizar todo lo financiero de un Job (Ingresos y Gastos).
    """
    # 1. Obtener parámetros de la URL (Query Params)
    try:
        start = int(request.args.get("start", 1))
        limit = int(request.args.get("limit", 100))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

    except ValueError:
        return {"error": "Los parámetros 'start' o 'limit' deben ser números enteros."}, 400

    # 2. Llamar a la función orquestadora
    result = sync_job_financials(
        realm_id=realm_id,
        job_code=job_code,
        start=start,
        limit=limit,
        dry_run=dry_run
    )

    # 3. Retornar el JSON unificado
    return result, 200


# ----------------------------------------------- #
# ------------- ENDPOINTS PARA OTROS ------------ #

# Endpoint para conseguir info de vendors reales
@qbo_bp.get("/vendors/<realm_id>")
def fetch_vendors(realm_id):

    start = int(request.args.get("start", 1))
    limit = int(request.args.get("limit", 100))

    data = get_vendors(
        realm_id=realm_id,
        start=start,
        limit=limit
    )
    return data, 200
