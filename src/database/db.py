import psycopg2
from psycopg2 import DatabaseError
from decouple import config

from flask_sqlalchemy import SQLAlchemy
from ..config import DATABASE_URL

db = SQLAlchemy()

def init_db(app):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está definida en el .env")
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    db.init_app(app)

def get_connection():
    # Devuelve la sesión ORM
    return db.session

# Función get_connection con estructura sencilla para conexión a base de datos sin ORM
"""
def get_connection():
    try:
        
        connect=psycopg2.connect(
            host=config('PGSQL_HOST'),
            user=config('PGSQL_USER'),
            password=config('PGSQL_PASSWORD'),
            database=config('PGSQL_DATABASE'),
            port=5433,
        )
        
        return connect
    except DatabaseError as ex:
        raise ex
"""