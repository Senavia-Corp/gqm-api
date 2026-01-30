
import requests
import time

from src.config import (
    BASE_URL,
    PODIO_CLIENT_ID,
    PODIO_CLIENT_SECRET,
    PODIO_APPS,
    get_podio_app_credentials
)
from src.utils.middleware.logs.logs import logger
from src.utils.middleware.retries.retries import retry_api


# =====================================================
# Cache GLOBAL de token OAuth (por client_id)
# =====================================================
_token_cache = {
    "global": None
}


@retry_api(max_retries=3, backoff=2)
def get_podio_headers(app_type: str):

    app_type = app_type.upper()

    app_creds = get_podio_app_credentials(app_type)

    cache_key = app_type

    if cache_key not in _token_cache:
        _token_cache[cache_key] = None

    if _token_cache[cache_key]:
        entry = _token_cache[cache_key]
        if time.time() < entry["expires"]:
            return {
                "Authorization": f"OAuth2 {entry['token']}",
                "Content-Type": "application/json"
            }

    logger.info(f"🔄 Generando token Podio para app {app_type}")

    data = {
        "grant_type": "app",
        "app_id": app_creds["APP_ID"],
        "app_token": app_creds["APP_TOKEN"],
        "client_id": PODIO_CLIENT_ID,
        "client_secret": PODIO_CLIENT_SECRET,
    }

    response = requests.post(f"{BASE_URL}/oauth/token", data=data)

    if response.status_code != 200:
        logger.error(
            f"❌ Podio OAuth error [{response.status_code}]: {response.text}"
        )
        response.raise_for_status()

    token_info = response.json()
    access_token = token_info.get("access_token")

    if not access_token:
        raise ValueError("❌ Podio no devolvió access_token")

    expires_in = token_info.get("expires_in", 28800)

    _token_cache[cache_key] = {
        "token": access_token,
        "expires": time.time() + expires_in - 60
    }

    logger.info(f"✅ Token Podio generado para {app_type}")

    return {
        "Authorization": f"OAuth2 {access_token}",
        "Content-Type": "application/json"
    }
