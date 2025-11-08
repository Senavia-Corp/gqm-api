import requests
from src.config import (
    BASE_URL,
    PODIO_TAP_APP_ID,
    PODIO_TAP_APP_TOKEN,
    PODIO_CLIENT_ID,
    PODIO_CLIENT_SECRET,
)


def get_podio_headers():
    """
    Retorna headers para autenticarse en Podio usando App Token.
    """
    url = f"{BASE_URL}/oauth/token"
    data = {
        "grant_type": "app",
        "app_id": PODIO_TAP_APP_ID,
        "app_token": PODIO_TAP_APP_TOKEN,
        "client_id": PODIO_CLIENT_ID,
        "client_secret": PODIO_CLIENT_SECRET,
    }

    response = requests.post(url, data=data)
    response.raise_for_status()  # lanza error si no es 200

    token_info = response.json()
    access_token = token_info.get("access_token")

    if not access_token:
        raise ValueError("No se pudo obtener access_token de Podio.")

    return {
        "Authorization": f"OAuth2 {access_token}",
        "Content-Type": "application/json"
    }
