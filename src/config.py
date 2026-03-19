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

# CREDENCIALES REALES:
# Credenciales de la App Clients
PODIO_CLIENTS_APP_ID = os.getenv("PODIO_CLIENTS_APP_ID")
PODIO_CLIENTS_APP_TOKEN = os.getenv("PODIO_CLIENTS_APP_TOKEN")
# Credenciales de la App Property Mgmt Co.
PODIO_PAMGMTCO_APP_ID = os.getenv("PODIO_PAMGMTCO_APP_ID")
PODIO_PAMGMTCO_APP_TOKEN = os.getenv("PODIO_PAMGMTCO_APP_TOKEN")
# Credenciales de la App Subcontractors
PODIO_SUBCONTRACTOR_APP_ID = os.getenv("PODIO_SUBCONTRACTOR_APP_ID")
PODIO_SUBCONTRACTOR_APP_TOKEN = os.getenv("PODIO_SUBCONTRACTOR_APP_TOKEN")
# Credenciales de la App Building Department:
PODIO_BLDGDEPT_APP_ID = os.getenv("PODIO_BLDGDEPT_APP_ID")
PODIO_BLDGDEPT_APP_TOKEN = os.getenv("PODIO_BLDGDEPT_APP_TOKEN")
# Credenciales de las Apps QID
# 2026
PODIO_QID2026_APP_ID = os.getenv("PODIO_QID2026_APP_ID")
PODIO_QID2026_APP_TOKEN = os.getenv("PODIO_QID2026_APP_TOKEN")
# 2025
PODIO_QID2025_APP_ID = os.getenv("PODIO_QID2025_APP_ID")
PODIO_QID2025_APP_TOKEN = os.getenv("PODIO_QID2025_APP_TOKEN")
# 2024
PODIO_QID2024_APP_ID = os.getenv("PODIO_QID2024_APP_ID")
PODIO_QID2024_APP_TOKEN = os.getenv("PODIO_QID2024_APP_TOKEN")
# 2023
PODIO_QID2023_APP_ID = os.getenv("PODIO_QID2023_APP_ID")
PODIO_QID2023_APP_TOKEN = os.getenv("PODIO_QID2023_APP_TOKEN")
# Credenciales de las Apps PTL
# 2026
PODIO_PTL2026_APP_ID = os.getenv("PODIO_PTL2026_APP_ID")
PODIO_PTL2026_APP_TOKEN = os.getenv("PODIO_PTL2026_APP_TOKEN")
# 2025
PODIO_PTL2025_APP_ID = os.getenv("PODIO_PTL2025_APP_ID")
PODIO_PTL2025_APP_TOKEN = os.getenv("PODIO_PTL2025_APP_TOKEN")
# 2024
PODIO_PTL2024_APP_ID = os.getenv("PODIO_PTL2024_APP_ID")
PODIO_PTL2024_APP_TOKEN = os.getenv("PODIO_PTL2024_APP_TOKEN")
# 2023
PODIO_PTL2023_APP_ID = os.getenv("PODIO_PTL2023_APP_ID")
PODIO_PTL2023_APP_TOKEN = os.getenv("PODIO_PTL2023_APP_TOKEN")
# Credenciales de las Apps PAR
# 2026
PODIO_PAR2026_APP_ID = os.getenv("PODIO_PAR2026_APP_ID")
PODIO_PAR2026_APP_TOKEN = os.getenv("PODIO_PAR2026_APP_TOKEN")
# 2025
PODIO_PAR2025_APP_ID = os.getenv("PODIO_PAR2025_APP_ID")
PODIO_PAR2025_APP_TOKEN = os.getenv("PODIO_PAR2025_APP_TOKEN")
# 2024
PODIO_PAR2024_APP_ID = os.getenv("PODIO_PAR2024_APP_ID")
PODIO_PAR2024_APP_TOKEN = os.getenv("PODIO_PAR2024_APP_TOKEN")
# 2023
PODIO_PAR2023_APP_ID = os.getenv("PODIO_PAR2023_APP_ID")
PODIO_PAR2023_APP_TOKEN = os.getenv("PODIO_PAR2023_APP_TOKEN")

# Credenciales de Cloudinary
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

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
    "TAS_TAP_APP_TOKEN": TAS_TAP_APP_TOKEN,

    "PODIO_CLIENTS_APP_ID": PODIO_CLIENTS_APP_ID,
    "PODIO_CLIENTS_APP_TOKEN": PODIO_CLIENTS_APP_TOKEN,
    "PODIO_PAMGMTCO_APP_ID": PODIO_PAMGMTCO_APP_ID,
    "PODIO_PAMGMTCO_APP_TOKEN": PODIO_PAMGMTCO_APP_TOKEN,
    "PODIO_SUBCONTRACTOR_APP_ID": PODIO_SUBCONTRACTOR_APP_ID,
    "PODIO_SUBCONTRACTOR_APP_TOKEN": PODIO_SUBCONTRACTOR_APP_TOKEN,
    "PODIO_BLDGDEPT_APP_ID": PODIO_BLDGDEPT_APP_ID,
    "PODIO_BLDGDEPT_APP_TOKEN": PODIO_BLDGDEPT_APP_TOKEN,

    # QID reales
    "PODIO_QID2026_APP_ID": PODIO_QID2026_APP_ID,
    "PODIO_QID2026_APP_TOKEN": PODIO_QID2026_APP_TOKEN,
    "PODIO_QID2025_APP_ID": PODIO_QID2025_APP_ID,
    "PODIO_QID2025_APP_TOKEN": PODIO_QID2025_APP_TOKEN,
    "PODIO_QID2024_APP_ID": PODIO_QID2024_APP_ID,
    "PODIO_QID2024_APP_TOKEN": PODIO_QID2024_APP_TOKEN,
    "PODIO_QID2023_APP_ID": PODIO_QID2023_APP_ID,
    "PODIO_QID2023_APP_TOKEN": PODIO_QID2023_APP_TOKEN,

    # PTL reales
    "PODIO_PTL2026_APP_ID": PODIO_PTL2026_APP_ID,
    "PODIO_PTL2026_APP_TOKEN": PODIO_PTL2026_APP_TOKEN,
    "PODIO_PTL2025_APP_ID": PODIO_PTL2025_APP_ID,
    "PODIO_PTL2025_APP_TOKEN": PODIO_PTL2025_APP_TOKEN,
    "PODIO_PTL2024_APP_ID": PODIO_PTL2024_APP_ID,
    "PODIO_PTL2024_APP_TOKEN": PODIO_PTL2024_APP_TOKEN,
    "PODIO_PTL2023_APP_ID": PODIO_PTL2023_APP_ID,
    "PODIO_PTL2023_APP_TOKEN": PODIO_PTL2023_APP_TOKEN,

    # PAR reales
    "PODIO_PAR2026_APP_ID": PODIO_PAR2026_APP_ID,
    "PODIO_PAR2026_APP_TOKEN": PODIO_PAR2026_APP_TOKEN,
    "PODIO_PAR2025_APP_ID": PODIO_PAR2025_APP_ID,
    "PODIO_PAR2025_APP_TOKEN": PODIO_PAR2025_APP_TOKEN,
    "PODIO_PAR2024_APP_ID": PODIO_PAR2024_APP_ID,
    "PODIO_PAR2024_APP_TOKEN": PODIO_PAR2024_APP_TOKEN,
    "PODIO_PAR2023_APP_ID": PODIO_PAR2023_APP_ID,
    "PODIO_PAR2023_APP_TOKEN": PODIO_PAR2023_APP_TOKEN,

}.items() if not v]

if _missing:
    print(f"[WARN] Faltan variables en .env: {', '.join(_missing)}")


# Mapa de Apps de Podio
# --- APPS ESTÁTICAS (No dependen del año) ---
PODIO_APPS = {
    # Test de Jobs
    "QID": {"APP_ID": QID_TAP_APP_ID, "APP_TOKEN": QID_TAP_APP_TOKEN},
    "PTL": {"APP_ID": PTL_TAP_APP_ID, "APP_TOKEN": PTL_TAP_APP_TOKEN},
    "PAR": {"APP_ID": PAR_TAP_APP_ID, "APP_TOKEN": PAR_TAP_APP_TOKEN},
    # Test de Tasks
    "TASK": {"APP_ID": TAS_TAP_APP_ID, "APP_TOKEN": TAS_TAP_APP_TOKEN},

    # Credencials reales
    "CLI": {
        "APP_ID": PODIO_CLIENTS_APP_ID,
        "APP_TOKEN": PODIO_CLIENTS_APP_TOKEN,
    },
    "PMC": {
        "APP_ID": PODIO_PAMGMTCO_APP_ID,
        "APP_TOKEN": PODIO_PAMGMTCO_APP_TOKEN,
    },
    "SUBC": {
        "APP_ID": PODIO_SUBCONTRACTOR_APP_ID,
        "APP_TOKEN": PODIO_SUBCONTRACTOR_APP_TOKEN,
    },
    "BDEP": {
        "APP_ID": PODIO_BLDGDEPT_APP_ID,
        "APP_TOKEN": PODIO_BLDGDEPT_APP_TOKEN,
    },
}

# --- APPS DINÁMICAS (JOBS POR AÑO) ---
JOB_YEARS = [2023, 2024, 2025, 2026]
JOB_TYPES = ["QID", "PTL", "PAR"]

PODIO_JOB_APPS = {}

# Verificador de variables faltantes para los Jobs
_missing_jobs = []

for year in JOB_YEARS:
    PODIO_JOB_APPS[year] = {}
    for j_type in JOB_TYPES:
        # Construye el nombre de la variable: Ej. PODIO_QID2026_APP_ID
        env_id_name = f"PODIO_{j_type}{year}_APP_ID"
        env_token_name = f"PODIO_{j_type}{year}_APP_TOKEN"

        app_id = os.getenv(env_id_name)
        app_token = os.getenv(env_token_name)

        # Validación rápida
        if not app_id or not app_token:
            _missing_jobs.append(f"{j_type}{year}")

        PODIO_JOB_APPS[year][j_type] = {
            "APP_ID": app_id,
            "APP_TOKEN": app_token
        }

if _missing_jobs:
    print(
        f"[WARN] Faltan credenciales en .env para los Jobs: {', '.join(_missing_jobs)}")


# Para apps estáticas
def get_podio_app_credentials(app_type: str):
    """
    Devuelve APP_ID y APP_TOKEN según app_type.
    """
    app_type = app_type.upper()
    if app_type not in PODIO_APPS:
        raise ValueError(f"Tipo de app inválido: {app_type}")
    return PODIO_APPS[app_type]


# Para apps dinámicas (Jobs)
def get_job_app_credentials(year: int, job_type: str):
    """
    Para apps dinámicas de Jobs.
    Uso: get_job_app_credentials(2025, 'QID')
    """
    if year not in PODIO_JOB_APPS:
        raise ValueError(f"Año no configurado: {year}")
    if job_type not in PODIO_JOB_APPS[year]:
        raise ValueError(f"Tipo de Job inválido: {job_type}")

    return PODIO_JOB_APPS[year][job_type]


# URL de Postgres
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("[ERROR] DATABASE_URL no está configurada en .env")

# URL PARA WEBHOOK DE PODIO
PUBLIC_URL = os.getenv("PUBLIC_URL")
