from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.exc import SQLAlchemyError
from decouple import config

# Todos los modelos (para evitar problemas con las relaciones en la creación de las tablas en la db)
from src.models import *  # noqa

# Configuración para PostgreSQL
DATABASE_URL = config("DATABASE_URL")
# Ver que existan las credenciales
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en el .env")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,    # Verifica la conexión antes de usarla (evita SSL stale connections)
    pool_recycle=1800,     # Recicla conexiones cada 30 min para evitar timeouts del servidor
)


def get_session():
    # Devuelve sesion lista para usar
    return Session(engine)
