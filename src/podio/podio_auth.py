
import requests
import time
from src.config import (
    BASE_URL,
    PODIO_CLIENT_ID,
    PODIO_CLIENT_SECRET,
    get_podio_app_credentials
)
from src.utils.middleware.logs.logs import logger
from src.utils.middleware.retries.retries import retry_api


# Cache de tokens por app: {"QID": {"token": "...", "expires": 123456}}
_token_cache = {}


def _token_is_valid(app_type: str) -> bool:

    # Retorna True si el token de esa app no ha expirado.

    if app_type not in _token_cache:
        return False

    entry = _token_cache[app_type]
    return time.time() < entry["expires"]


@retry_api(max_retries=3, backoff=2)
def get_podio_headers(app_type: str):

    app_type = app_type.upper()

    # Obtener credenciales según app
    try:
        creds = get_podio_app_credentials(app_type)
    except ValueError as e:
        logger.error(f"❌ Tipo de app inválido: {app_type}")
        raise e

    APP_ID = creds["APP_ID"]
    APP_TOKEN = creds["APP_TOKEN"]

    # 1. Token aún válido
    if _token_is_valid(app_type):
        return {
            "Authorization": f"OAuth2 {_token_cache[app_type]['token']}",
            "Content-Type": "application/json"
        }

    logger.info(f"🔄 Generando nuevo token para Podio App [{app_type}]...")

    # 2. Generar nuevo token
    url = f"{BASE_URL}/oauth/token"
    data = {
        "grant_type": "app",
        "app_id": APP_ID,
        "app_token": APP_TOKEN,
        "client_id": PODIO_CLIENT_ID,
        "client_secret": PODIO_CLIENT_SECRET,
    }

    response = requests.post(url, data=data)
    response.raise_for_status()

    token_info = response.json()
    access_token = token_info.get("access_token")
    expires_in = token_info.get("expires_in", 3600)

    if not access_token:
        raise ValueError(
            f"No se pudo obtener access_token de Podio para app {app_type}.")

    # Cachear token
    _token_cache[app_type] = {
        "token": access_token,
        "expires": time.time() + expires_in - 30
    }

    logger.info(f"✅ Token para Podio App [{app_type}] generado y almacenado.")

    return {
        "Authorization": f"OAuth2 {access_token}",
        "Content-Type": "application/json"
    }
