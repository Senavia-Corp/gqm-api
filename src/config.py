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

#Credenciales del App Test Admin Panel
PODIO_TEST_ADMIN_PANEL_APP_ID = os.getenv("PODIO_TEST_ADMIN_PANEL_APP_ID")
PODIO_TEST_ADMIN_PANEL_APP_TOKEN = os.getenv("PODIO_TEST_ADMIN_PANEL_APP_TOKEN")
#Credenciales del App QID2025
PODIO_APP_ID = os.getenv("PODIO_APP_ID")
PODIO_APP_TOKEN = os.getenv("PODIO_APP_TOKEN")
#Credenciales del App Clients
PODIO_CLIENTS_APP_ID = os.getenv("PODIO_CLIENTS_APP_ID")
PODIO_CLIENTS_APP_TOKEN = os.getenv("PODIO_CLIENTS_APP_TOKEN")
#Credenciales del App Subcontractors
PODIO_SUBCONTRACTORS_APP_ID = os.getenv("PODIO_SUBCONTRACTORS_APP_ID")
PODIO_SUBCONTRACTORS_APP_TOKEN = os.getenv("PODIO_SUBCONTRACTORS_APP_TOKEN")


_missing = [k for k, v in {
    "PODIO_CLIENT_ID": PODIO_CLIENT_ID,
    "PODIO_CLIENT_SECRET": PODIO_CLIENT_SECRET,
    "PODIO_APP_ID": PODIO_APP_ID,
    "PODIO_APP_TOKEN": PODIO_APP_TOKEN,
}.items() if not v]

if _missing:
    print(f"[WARN] Faltan variables en .env: {', '.join(_missing)}")
    
# URL de Postgres para SQLAlchemy-Hace parte de la DB
DATABASE_URL = os.getenv("DATABASE_URL") 