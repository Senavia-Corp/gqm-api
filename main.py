from flask import Flask
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
    app = create_app()
    app.run(debug=True)
