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


# =====================================================
# Cache GLOBAL de token OAuth (por app_type)
# =====================================================
_token_cache = {}


@retry_api(max_retries=3, backoff=2)
def get_podio_headers(app_type: str):
    logger.info("==========================================")
    logger.info("🔐 INICIANDO AUTENTICACIÓN PODIO")
    logger.info(f"📌 app_type recibido: {app_type}")

    app_type = app_type.upper()

    # -----------------------------------------
    # Obtener credenciales de la app
    # -----------------------------------------
    app_creds = get_podio_app_credentials(app_type)

    logger.info(f"📦 Credenciales obtenidas para {app_type}: {app_creds}")

    if not app_creds:
        raise ValueError(
            f"❌ get_podio_app_credentials devolvió None o vacío para app_type={app_type}"
        )

    app_id = app_creds.get("APP_ID")
    app_token = app_creds.get("APP_TOKEN")

    if not app_id or not app_token:
        raise ValueError(
            f"❌ Credenciales incompletas para {app_type}. "
            f"APP_ID={app_id}, APP_TOKEN={'SET' if app_token else None}"
        )

    # -----------------------------------------
    # Cache de token
    # -----------------------------------------
    if app_type not in _token_cache:
        _token_cache[app_type] = None

    cached = _token_cache[app_type]

    if cached:
        logger.info("🧠 Token encontrado en cache")
        logger.info(
            f"⏱ Expira en {int(cached['expires'] - time.time())} segundos"
        )

        if time.time() < cached["expires"]:
            logger.info("✅ Token aún válido, reutilizando")
            return {
                "Authorization": f"OAuth2 {cached['token']}",
                "Content-Type": "application/json"
            }

        logger.warning("⚠️ Token expirado, regenerando")

    # -----------------------------------------
    # Construcción del payload OAuth
    # -----------------------------------------
    payload = {
        "grant_type": "app",
        "app_id": app_id,
        "app_token": app_token,
        "client_id": PODIO_CLIENT_ID,
        "client_secret": PODIO_CLIENT_SECRET,
    }

    logger.info("📤 Enviando payload OAuth a Podio:")
    logger.info(
        f"   grant_type=app | app_id={app_id} | "
        f"client_id={PODIO_CLIENT_ID}"
    )

    url = f"{BASE_URL}/oauth/token"
    logger.info(f"🌐 URL OAuth Podio: {url}")

    # -----------------------------------------
    # Request OAuth
    # -----------------------------------------
    response = requests.post(url, data=payload)

    logger.info(f"📥 Respuesta Podio status: {response.status_code}")
    logger.info(f"📥 Respuesta Podio body: {response.text}")

    if response.status_code != 200:
        logger.error(
            f"❌ Podio OAuth error [{response.status_code}]: {response.text}"
        )
        response.raise_for_status()

    # -----------------------------------------
    # Procesar token
    # -----------------------------------------
    token_info = response.json()
    access_token = token_info.get("access_token")

    if not access_token:
        raise ValueError(
            f"❌ Podio NO devolvió access_token. Respuesta: {token_info}"
        )

    expires_in = token_info.get("expires_in", 28800)

    _token_cache[app_type] = {
        "token": access_token,
        "expires": time.time() + expires_in - 60
    }

    logger.info(
        f"✅ Token Podio generado correctamente para {app_type} "
        f"(expira en {expires_in} seg)"
    )

    return {
        "Authorization": f"OAuth2 {access_token}",
        "Content-Type": "application/json"
    }
