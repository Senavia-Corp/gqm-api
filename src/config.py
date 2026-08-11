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

# Entorno de la aplicación: "test" o "production" (default: production)
APP_ENV = os.getenv("APP_ENV", "production").lower()


def _bandera(nombre: str) -> bool:
    return os.getenv(nombre, "").strip().lower() in ("1", "true", "yes", "si", "sí")


# Corta TODA escritura SALIENTE hacia Podio, en cualquier entorno. Se enciende
# durante la ventana de reconciliación para que ni una importación ni un
# `PATCH /jobs/X?sync_podio=true` desde el panel puedan tocar las apps mientras
# se comparan contadores.
#
# NO afecta a las escrituras ENTRANTES: los webhooks de Podio guardan en la BD
# por `upsert_job_from_item`, que no pasa por `PodioBaseService`. Si esta bandera
# matara también lo entrante, el sync moriría durante la ventana y la
# divergencia crecería justo mientras se arregla.
PODIO_READONLY = _bandera("PODIO_READONLY")

# Exige que el item que se va a escribir pertenezca EXACTAMENTE a la app del
# servicio que lo escribe, no solo a alguna app de la lista blanca. Es lo único
# que atrapa un update/delete apuntando al año equivocado.
#
# En producción NO puede encenderse todavía: mientras M1/M2 no hayan corrido
# allí, el año resuelto es None para los 510 PTL y equivocado en 88 jobs, así
# que esas escrituras pasarían de "ir a la app equivocada" a fallar en seco.
PODIO_STRICT_APP_MATCH = _bandera("PODIO_STRICT_APP_MATCH") or APP_ENV == "test"

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
    # REG-081: en producción, arrancar sin las credenciales REALES es
    # fail-fast. Las *_TAP se excluyen a propósito: deben estar AUSENTES en
    # prod (si se definieran, el registro de hooks apuntaría a apps de
    # prueba). En test/local solo se avisa.
    _prod_missing = [k for k in _missing if "_TAP_" not in k]
    if APP_ENV == "production" and _prod_missing:
        raise RuntimeError(
            f"Faltan variables de entorno obligatorias: {', '.join(_prod_missing)}")
    print(f"[WARN] Faltan variables en .env: {', '.join(_missing)}")


# Mapa de Apps de Podio
# --- APPS ESTÁTICAS (No dependen del año) ---
PODIO_APPS = {
    # Test de Jobs
    "QID": {"APP_ID": QID_TAP_APP_ID, "APP_TOKEN": QID_TAP_APP_TOKEN},
    "PTL": {"APP_ID": PTL_TAP_APP_ID, "APP_TOKEN": PTL_TAP_APP_TOKEN},
    "PAR": {"APP_ID": PAR_TAP_APP_ID, "APP_TOKEN": PAR_TAP_APP_TOKEN},
    # Test de Tasks

    # Credencials reales
    "CLI": {
        "APP_ID": CLI_TAP_APP_ID if APP_ENV == "test" else PODIO_CLIENTS_APP_ID,
        "APP_TOKEN": CLI_TAP_APP_TOKEN if APP_ENV == "test" else PODIO_CLIENTS_APP_TOKEN,
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

# Mapa de credenciales TAP (test) por tipo de job
_TAP_CREDS = {
    "QID": (QID_TAP_APP_ID, QID_TAP_APP_TOKEN),
    "PTL": (PTL_TAP_APP_ID, PTL_TAP_APP_TOKEN),
    "PAR": (PAR_TAP_APP_ID, PAR_TAP_APP_TOKEN),
}

# Verificador de variables faltantes para los Jobs
_missing_jobs = []

if APP_ENV == "test":
    print("[INFO] APP_ENV=test → usando credenciales TAP 2 (prueba) para todos los Jobs")

for year in JOB_YEARS:
    PODIO_JOB_APPS[year] = {}
    for j_type in JOB_TYPES:
        if APP_ENV == "test":
            # En modo test se reutilizan las credenciales TAP para todos los años
            app_id, app_token = _TAP_CREDS.get(j_type, (None, None))
        else:
            # En producción se usan las credenciales reales por año
            app_id = os.getenv(f"PODIO_{j_type}{year}_APP_ID")
            app_token = os.getenv(f"PODIO_{j_type}{year}_APP_TOKEN")

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


def app_ids_configurados() -> set[str]:
    """Los app_id de Podio que ESTA configuración puede tocar.

    Con `APP_ENV=test` son exactamente las apps TAP (de prueba); en producción,
    las reales. Sirve de lista blanca para la guarda de escritura saliente: ver
    `PodioBaseService._exigir_app_permitida`.
    """
    ids = set()
    for cred in PODIO_APPS.values():
        if cred.get("APP_ID"):
            ids.add(str(cred["APP_ID"]))
    for por_tipo in PODIO_JOB_APPS.values():
        for cred in por_tipo.values():
            if cred.get("APP_ID"):
                ids.add(str(cred["APP_ID"]))
    return ids


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