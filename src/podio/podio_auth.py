import requests
import time
from src.config import (
    BASE_URL,
    PODIO_TAP_APP_ID,
    PODIO_TAP_APP_TOKEN,
    PODIO_CLIENT_ID,
    PODIO_CLIENT_SECRET,
)
from src.utils.middleware.logs.logs import logger
from src.utils.middleware.retries.retries import retry_api


# Cache del token (para mejorar la optimización de la conexion con Podio)
_cached_token = None
_token_expiration = 0  # timestamp UNIX


def _token_is_valid():
    """Retorna True si el token no ha expirado."""
    return _cached_token and time.time() < _token_expiration


@retry_api(max_retries=3, backoff=2)
def get_podio_headers():
    """
    Retorna headers para autenticarse en Podio usando App Token.
    """

    global _cached_token, _token_expiration

    # 1. Si el token sigue siendo válido:
    if _token_is_valid():
        return {
            "Authorization": f"OAuth2 {_cached_token}",
            "Content-Type": "application/json"
        }

    logger.info("🔄 Generando nuevo token de Podio...")

    # 2. Si el token expiró:
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
    expires_in = token_info.get("expires_in", 3600)  # 1 hora

    if not access_token:
        raise ValueError("No se pudo obtener access_token de Podio.")

    # 3. Guardar en cache:
    _cached_token = access_token
    _token_expiration = time.time() + expires_in - 30  # le restamos 30s por seguridad

    logger.info("✅ Token de Podio generado y almacenado en cache.")

    return {
        "Authorization": f"OAuth2 {_cached_token}",
        "Content-Type": "application/json"
    }
