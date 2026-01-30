
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


# =====================================================
# Obtener headers OAuth2 para Podio
# Token ÚNICO reutilizable para todas las apps
# =====================================================
@retry_api(max_retries=3, backoff=2)
def get_podio_headers(app_type: str):
    """
    Retorna headers OAuth2 válidos para Podio.

    - Usa App Authentication Flow
    - Genera UN SOLO token global
    - El app_type se usa solo para validar que la app existe
    """

    app_type = app_type.upper()

    # -------------------------------------------------
    # 1. Validar que la app existe (control lógico)
    # -------------------------------------------------
    try:
        get_podio_app_credentials(app_type)
    except ValueError as e:
        logger.error(f"❌ Tipo de app inválido: {app_type}")
        raise e

    # -------------------------------------------------
    # 2. Reutilizar token si aún es válido
    # -------------------------------------------------
    if _token_cache["global"]:
        entry = _token_cache["global"]
        if time.time() < entry["expires"]:
            return {
                "Authorization": f"OAuth2 {entry['token']}",
                "Content-Type": "application/json"
            }

    # -------------------------------------------------
    # 3. Generar nuevo token GLOBAL
    # -------------------------------------------------
    logger.info("🔄 Generando token GLOBAL de Podio (App Auth Flow)...")

    # Usamos cualquier app válida SOLO para emitir el token
    first_app = next(iter(PODIO_APPS.values()))

    data = {
        "grant_type": "app",
        "app_id": first_app["APP_ID"],
        "app_token": first_app["APP_TOKEN"],
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
    expires_in = token_info.get("expires_in", 28800)  # 8 horas

    if not access_token:
        raise ValueError("❌ Podio no devolvió access_token")

    # -------------------------------------------------
    # 4. Cachear token global
    # -------------------------------------------------
    _token_cache["global"] = {
        "token": access_token,
        "expires": time.time() + expires_in - 60  # margen de seguridad
    }

    logger.info("✅ Token GLOBAL de Podio generado y cacheado.")

    return {
        "Authorization": f"OAuth2 {access_token}",
        "Content-Type": "application/json"
    }
