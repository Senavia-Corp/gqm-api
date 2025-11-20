from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.exc import SQLAlchemyError
from decouple import config

# Configuración para PostgreSQL
DATABASE_URL = config("DATABASE_URL")
# Ver que existan las credenciales
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en el .env")

engine = create_engine(DATABASE_URL, echo=False)


def init_sqlmodel_db(app=None):
    try:
        # Crea las tablas en la db
        SQLModel.metadata.create_all(engine)

    except SQLAlchemyError as e:  # Si la db no responde o no conecta
        print("Error CRÍTICO: Fallo al inicializar o conectar con la base de datos.")
        print(f"Detalle del error: {e}")
        raise RuntimeError(
            "No se pudo establecer una conexión inicial con la base de datos."
        ) from e  # Útil para depurar

    except Exception as e:  # Captura cualquier otro error inesperado
        print(f"Error inesperado durante la inicialización de la DB: {e}")
        raise  # raise al final del except para que la aplicación se detenga


def get_session():
    # Devuelve sesion lista para usar
    return Session(engine)
