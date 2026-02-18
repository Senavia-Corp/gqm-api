import requests
import time
from typing import Optional

from src.config import (
    BASE_URL,
    PODIO_CLIENT_ID,
    PODIO_CLIENT_SECRET,
    get_podio_app_credentials,
    get_job_app_credentials
)
from src.utils.middleware.logs.logs import logger
from src.utils.middleware.retries.retries import retry_api


# =====================================================
# Cache GLOBAL de token OAuth
# Claves tipo "CLI" o "QID_2026"
# =====================================================
_token_cache = {}


@retry_api(max_retries=3, backoff=2)
def get_podio_headers(app_type: str, year: Optional[int] = None):
    """
    Obtiene headers de autenticación para Podio.

    Args:
        app_type (str): Tipo de app ('CLI', 'PMC', 'QID', 'PTL', etc.)
        year (int, optional): Año del Job (ej: 2026). Solo necesario para Jobs.
    """
    logger.info("==========================================")
    logger.info("🔐 INICIANDO AUTENTICACIÓN PODIO")

    app_type = app_type.upper()

    # -----------------------------------------
    # 1. Definir la clave única para el Cache
    # -----------------------------------------
    if year:
        # Si es un Job, la clave es compuesta: QID_2026
        cache_key = f"{app_type}_{year}"
        logger.info(
            f"📌 Buscando credenciales para JOB: {app_type} del año {year}")
    else:
        # Si es estática, la clave es simple: CLI
        cache_key = app_type
        logger.info(f"📌 Buscando credenciales para APP ESTÁTICA: {app_type}")

    # -----------------------------------------
    # 2. Obtener credenciales (Lógica Híbrida)
    # -----------------------------------------
    try:
        if year is not None:
            app_creds = get_job_app_credentials(year, app_type)
        else:
            # Usamos la función clásica para apps estáticas
            app_creds = get_podio_app_credentials(app_type)

        # DEBUG: Ver qué devolvió la función de credenciales
        logger.info(f"DEBUG CREDS: Tipo devuelto: {type(app_creds)}")
        logger.info(
            f"DEBUG CREDS: Keys disponibles: {list(app_creds.keys()) if isinstance(app_creds, dict) else 'N/A'}")

    except ValueError as e:
        logger.error(f"❌ Error buscando credenciales: {e}")
        raise e

    logger.info(f"📦 Credenciales obtenidas para {cache_key}")

    if not app_creds:
        raise ValueError(f"❌ Credenciales vacías para {cache_key}")

    app_id = app_creds.get("APP_ID")
    app_token = app_creds.get("APP_TOKEN")

    if not app_id or not app_token:
        raise ValueError(
            f"❌ Credenciales incompletas para {cache_key}. "
            f"APP_ID={app_id}, APP_TOKEN={'SET' if app_token else None}"
        )

    # -----------------------------------------
    # 3. Revisar Cache
    # -----------------------------------------
    if cache_key not in _token_cache:
        _token_cache[cache_key] = None

    cached = _token_cache[cache_key]

    if cached:
        time_left = int(cached['expires'] - time.time())
        logger.info(f"🧠 Token encontrado en cache para {cache_key}")

        if time.time() < cached["expires"]:
            logger.info(
                f"✅ Token aún válido (restan {time_left}s), reutilizando")
            return {
                "Authorization": f"OAuth2 {cached['token']}",
                "Content-Type": "application/json"
            }

        logger.warning("⚠️ Token expirado, regenerando")

    # -----------------------------------------
    # 4. Construcción del payload OAuth
    # -----------------------------------------
    payload = {
        "grant_type": "app",
        "app_id": app_id,
        "app_token": app_token,
        "client_id": PODIO_CLIENT_ID,
        "client_secret": PODIO_CLIENT_SECRET,
    }

    logger.info(f"📤 Solicitando nuevo token para app_id={app_id}...")

    url = f"{BASE_URL}/oauth/token"

    # -----------------------------------------
    # 5. Request OAuth
    # -----------------------------------------
    response = requests.post(url, data=payload)

    if response.status_code != 200:
        logger.error(
            f"❌ Podio OAuth error [{response.status_code}]: {response.text}")
        response.raise_for_status()

    # -----------------------------------------
    # 6. Procesar token y guardar en Cache
    # -----------------------------------------
    token_info = response.json()
    access_token = token_info.get("access_token")

    if not access_token:
        raise ValueError(
            f"❌ Podio NO devolvió access_token. Respuesta: {token_info}")

    expires_in = token_info.get("expires_in", 28800)

    # Guardamos en cache usando la cache_key compuesta
    _token_cache[cache_key] = {
        "token": access_token,
        "expires": time.time() + expires_in - 60
    }

    logger.info(
        f"✅ Nuevo Token generado para {cache_key} (expira en {expires_in}s)")

    return {
        "Authorization": f"OAuth2 {access_token}",
        "Content-Type": "application/json"
    }
