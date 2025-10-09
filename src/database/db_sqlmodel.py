from sqlmodel import SQLModel, create_engine, Session
from decouple import config

# Configuración para PostgreSQL
DATABASE_URL = config("DATABASE_URL")
# Ver que existan las credenciales
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en el .env")

engine = create_engine(DATABASE_URL, echo=True)


def init_sqlmodel_db(app=None):
    # Crea las tablas en la db
    SQLModel.metadata.create_all(engine)


def get_session():
    # Devuelve sesion lista para usar
    return Session(engine)
