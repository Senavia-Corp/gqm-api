from flask import Blueprint, request
import os
import base64
import requests

# RUTA PARA CONSEGUIR CODE PARA OBTENER TOKENS:
qbo_oauth_bp = Blueprint("qbo_oauth_bp", __name__)


@qbo_oauth_bp.route("/callback")
def qbo_callback():
    code = request.args.get("code")
    realmId = request.args.get("realmId")

    print("CODE:", code)
    print("REALM:", realmId)

    tokens = exchange_code_for_tokens(code)
    print("TOKENS:", tokens)

    return "OK", 200


# FUNCION PARA INTERCAMBIAR EL CODE POR LOS TOKENS (AUTOMÁTICO)
def exchange_code_for_tokens(code):
    client_id = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")
    redirect_uri = os.getenv("QBO_REDIRECT_URI")

    # Basic Auth en base64
    auth_header = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()

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

    print("TOKEN RESPONSE:", response.text)
    return response.json()


# FUNCIÓN PARA CONSEGUIR ACCESS TOKEN CUANDO SE EXPIRE DESPUES DE 1 HORA
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
