from decouple import config
import os
from dotenv import load_dotenv

# ======== Archivo de Configuración para la BD ========
class Config:
    SECRET_KEY=config('SECRET_KEY')

class DevelopmentConfig(Config):
    DEBUG=True

config={
    'development': DevelopmentConfig
}

# ======== Archivo de Configuración para la conexión a Podio ========
load_dotenv()

# Endpoints Podio
BASE_URL = "https://api.podio.com"
TOKEN_URL = "https://api.podio.com/oauth/token/v2"

# Credenciales (desde .env)
PODIO_CLIENT_ID = os.getenv("PODIO_CLIENT_ID")
PODIO_CLIENT_SECRET = os.getenv("PODIO_CLIENT_SECRET")
PODIO_APP_ID = os.getenv("PODIO_APP_ID")
PODIO_APP_TOKEN = os.getenv("PODIO_APP_TOKEN")

_missing = [k for k, v in {
    "PODIO_CLIENT_ID": PODIO_CLIENT_ID,
    "PODIO_CLIENT_SECRET": PODIO_CLIENT_SECRET,
    "PODIO_APP_ID": PODIO_APP_ID,
    "PODIO_APP_TOKEN": PODIO_APP_TOKEN,
}.items() if not v]

if _missing:
    print(f"[WARN] Faltan variables en .env: {', '.join(_missing)}")