from flask import Flask
import sys
# Blueprints
from src.database.db import init_db, db  # Importados para ORM
from src.routes.Job import job_bp
from src.routes.Client import client_bp
from src.routes.Subcontractor import subcontractor_bp
# Intento con SQLModel:
from src.database.db_sqlmodel import init_sqlmodel_db
from src.routes.Supplier import supplier_bp


def create_app():
    app = Flask(__name__)

    # Inicializa ORM
    init_db(app)

    #  Crea tablas que no existan (NO borra nada).
    #   Es seguro dejarlo en dev; en prod se recomienda Alembic.
    with app.app_context():
        # db.create_all()
        init_sqlmodel_db()

    # Registrar blueprints
    app.register_blueprint(job_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(subcontractor_bp)
    app.register_blueprint(supplier_bp)

    # Ruta simple de home

    @app.get("/")
    def root():
        return "Home"

    return app


if __name__ == "__main__":
    try:
        app = create_app()
        app.run(debug=True)

    except RuntimeError as e:
        print(f"\n[ERROR CRÍTICO] La aplicación no pudo iniciar: {e}")
        # Para terminar la ejecución de un programa inmediatamente, indicando que fue por un error
        sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR FATAL] Fallo inesperado al iniciar: {e}")
        sys.exit(1)
