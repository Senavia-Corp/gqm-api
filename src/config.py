from decouple import config
import os
from dotenv import load_dotenv

# ======== Archivo de Configuración para la BD ========
load_dotenv()


class Config:
    SECRET_KEY = config('SECRET_KEY')


class DevelopmentConfig(Config):
    DEBUG = True


config = {
    'development': DevelopmentConfig
}

# ======== Archivo de Configuración para la conexión a Podio ========

# Endpoints Podio
BASE_URL = "https://api.podio.com"
TOKEN_URL = "https://api.podio.com/oauth/token"
# TOKEN_URL = "https://api.podio.com/oauth/token/v2"

# Credenciales (desde .env)
PODIO_CLIENT_ID = os.getenv("PODIO_CLIENT_ID")
PODIO_CLIENT_SECRET = os.getenv("PODIO_CLIENT_SECRET")

# Credenciales del App Test Admin 1 QID
QID_TAP_APP_ID = os.getenv("QID_TAP_APP_ID")
QID_TAP_APP_TOKEN = os.getenv("QID_TAP_APP_TOKEN")
# Credenciales del App Test Admin 2 PTL
PTL_TAP_APP_ID = os.getenv("PTL_TAP_APP_ID")
PTL_TAP_APP_TOKEN = os.getenv("PTL_TAP_APP_TOKEN")
# Credenciales del App Test Admin 3 PAR
PAR_TAP_APP_ID = os.getenv("PAR_TAP_APP_ID")
PAR_TAP_APP_TOKEN = os.getenv("PAR_TAP_APP_TOKEN")
# Credenciales del App Test Admin 4 Clients
CLI_TAP_APP_ID = os.getenv("CLI_TAP_APP_ID")
CLI_TAP_APP_TOKEN = os.getenv("CLI_TAP_APP_TOKEN")
# Credenciales del App Test Admin 5 Tasks
TAS_TAP_APP_ID = os.getenv("TAS_TAP_APP_ID")
TAS_TAP_APP_TOKEN = os.getenv("TAS_TAP_APP_TOKEN")

# Verificar que las credenciales esten en .env
_missing = [k for k, v in {
    "PODIO_CLIENT_ID": PODIO_CLIENT_ID,
    "PODIO_CLIENT_SECRET": PODIO_CLIENT_SECRET,
    "QID_TAP_APP_ID": QID_TAP_APP_ID,
    "QID_TAP_APP_TOKEN": QID_TAP_APP_TOKEN,
    "PTL_TAP_APP_ID": PTL_TAP_APP_ID,
    "PTL_TAP_APP_TOKEN": PTL_TAP_APP_TOKEN,
    "PAR_TAP_APP_ID": PAR_TAP_APP_ID,
    "PAR_TAP_APP_TOKEN": PAR_TAP_APP_TOKEN,
    "CLI_TAP_APP_ID": CLI_TAP_APP_ID,
    "CLI_TAP_APP_TOKEN": CLI_TAP_APP_TOKEN,
    "TAS_TAP_APP_ID": TAS_TAP_APP_ID,
    "TAS_TAP_APP_TOKEN": TAS_TAP_APP_TOKEN
}.items() if not v]

if _missing:
    print(f"[WARN] Faltan variables en .env: {', '.join(_missing)}")


# Mapa de Apps de Podio

PODIO_APPS = {
    "QID": {
        "APP_ID": QID_TAP_APP_ID,
        "APP_TOKEN": QID_TAP_APP_TOKEN,
    },
    "PTL": {
        "APP_ID": PTL_TAP_APP_ID,
        "APP_TOKEN": PTL_TAP_APP_TOKEN,
    },
    "PAR": {
        "APP_ID": PAR_TAP_APP_ID,
        "APP_TOKEN": PAR_TAP_APP_TOKEN,
    },
    "CLI": {
        "APP_ID": CLI_TAP_APP_ID,
        "APP_TOKEN": CLI_TAP_APP_TOKEN,
    },
    "TASK": {
        "APP_ID": TAS_TAP_APP_ID,
        "APP_TOKEN": TAS_TAP_APP_TOKEN,
    }
}


def get_podio_app_credentials(app_type: str):
    """
    Devuelve APP_ID y APP_TOKEN según app_type (QID, PTL, PAR, CLI).
    """
    app_type = app_type.upper()
    if app_type not in PODIO_APPS:
        raise ValueError(f"Tipo de app inválido: {app_type}")
    return PODIO_APPS[app_type]


# URL de Postgres
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("[ERROR] DATABASE_URL no está configurada en .env")


# URL PARA WEBHOOK DE PODIO
PUBLIC_URL = os.getenv("PUBLIC_URL")
