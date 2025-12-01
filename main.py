from src.config import PUBLIC_URL
from flask import Flask
import sys
# Middleware de logs para todos los request:
from src.utils.middleware.logs.request_logger import register_request_logger
# Conexion con base de datos:
from src.database.db_sqlmodel import init_sqlmodel_db
# Blueprints:
from src.routes.Job import job_bp
from src.routes.Links.JobLinks import job_member_bp, job_multiplier_bp
from src.routes.Client import client_bp
from src.routes.Subcontractor import subcontractor_bp
from src.routes.Supplier import supplier_bp
from src.routes.Tasks import tasks_bp
from src.routes.Member import member_bp
from src.routes.Technician import technician_bp
from src.routes.Skills import skills_bp
from src.routes.MultiplierR import multiplier_bp
from src.routes.Attachments import attachments_bp
from src.routes.PropertyManager import property_manager_bp
from src.routes.PropertyMgmtCo import property_mgmt_co_bp
from src.routes.Links.ClientPrManager import client_pr_manager_bp
# Rutas de login:
from src.routes.Login_auth import auth_bp
# Sincronizacion masiva de Podio a Postgre:
from src.routes.podio_routes.MasiveSync import sync_bp
# Rutas de webhooks:
from src.routes.Webhook_bp import webhook_bp
from src.routes.podio_routes.AdminHooks import admin_bp
# Rutas de Quickbooks sandbox
from src.routes.qbo_routes.sandbox_route import qbo_bp
from src.quickbooks.qbo_auth import qbo_oauth_bp

# Test
# from src.tests.debug_podio import debug_bp


def create_app():
    app = Flask(__name__)

    # Middleware de logs para todas las rutas
    register_request_logger(app)

    #  Crea tablas que no existan (NO borra nada).
    with app.app_context():
        init_sqlmodel_db()

    # Registrar blueprints
    app.register_blueprint(job_bp)
    app.register_blueprint(job_multiplier_bp)
    app.register_blueprint(job_member_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(subcontractor_bp)
    app.register_blueprint(supplier_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(member_bp)
    app.register_blueprint(technician_bp)
    app.register_blueprint(skills_bp)
    app.register_blueprint(multiplier_bp)
    app.register_blueprint(attachments_bp)
    app.register_blueprint(property_manager_bp)
    app.register_blueprint(property_mgmt_co_bp)
    app.register_blueprint(client_pr_manager_bp)

    # Ruta para login
    app.register_blueprint(auth_bp)

    # Rutas relacionadas con Podio
    # app.register_blueprint(sync_bp)  # Sincronización con Podio
    # app.register_blueprint(webhook_bp)  # Para recibir todos los webhooks
    # Para crear o eliminar los hooks de Podio
    app.register_blueprint(admin_bp)

    # Para conexion con sandbox de Quickbooks
    app.register_blueprint(qbo_bp)
    # app.register_blueprint(qbo_oauth_bp)  # Solo para conseguir los tokens

    # app.register_blueprint(debug_bp)  # test

    # Ruta simple

    @app.get("/")
    def root():
        return "API corriendo correctamente."

    return app


def validate_public_url():
    """
    Esta validación se usa solo cuando corres la app localmente.
    En Vercel no queremos que un import falle por esto.
    """
    print("🌐 URL pública actual:", PUBLIC_URL)

    if not PUBLIC_URL or "http" not in PUBLIC_URL:
        print("❌ ERROR: PUBLIC_URL no es válida. No se puede registrar el webhook.")
        # Puedes elegir: solo avisar o terminar el proceso local.
        sys.exit(1)

app = create_app()

if __name__ == "__main__":
    try:
        validate_public_url()
        
        app.run(debug=True, port=80)

    except RuntimeError as e:
        print(f"\n[ERROR CRÍTICO] La aplicación no pudo iniciar: {e}")
        # Para terminar la ejecución de un programa inmediatamente, indicando que fue por un error
        sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR FATAL] Fallo inesperado al iniciar: {e}")
        sys.exit(1)
