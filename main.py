from src.config import PUBLIC_URL
from flask import Flask
from flask_cors import CORS
import sys
# Middleware de logs para todos los request:
from src.utils.middleware.logs.request_logger import register_request_logger
# Blueprints:
from src.routes.Job import job_bp
from src.routes.Links.JobLinks import job_member_bp, job_multiplier_bp, job_subcontractor_bp, job_payment_unit_bp
from src.routes.Client import client_bp
from src.routes.Subcontractor import subcontractor_bp
from src.routes.Supplier import supplier_bp
from src.routes.Tasks import tasks_bp
from src.routes.Member import member_bp
from src.routes.Technician import technician_bp
from src.routes.Skills import skills_bp
from src.routes.MultiplierR import multiplier_bp
from src.routes.Attachments import attachments_bp
from src.routes.Manager import manager_bp
from src.routes.ParentMgmtCo import parent_mgmt_co_bp
from src.routes.PaymentUnit import payment_unit_bp
from src.routes.Links.ClientLinks import client_manager_bp, client_member_bp
from src.routes.EstimateCost import estimate_bp
from src.routes.Order import order_bp
from src.routes.Role import role_bp
from src.routes.Permission import permission_bp
from src.routes.Links.PermissionLinks import permission_role_bp, permission_member_bp, permission_tech_bp
from src.routes.ChangeOrder import change_order_bp
from src.routes.Opportunities import opportunities_bp
from src.routes.TLActivity import tlactivity_bp
from src.routes.FinancialDocItem import fdoc_item_bp
from src.routes.FinancialDocument import fdocument_bp
from src.routes.FinancialTransaction import ftransaction_bp
from src.routes.Links.FinancialLinks import fdocument_ftransaction_bp
from src.routes.Purchase import purchase_bp
from src.routes.PurchaseOrder import purchase_order_bp
from src.routes.PurchaseOrderItem import purchase_order_item_bp
from src.routes.Links.PurchaseSupplierLink import purchase_supplier_bp
# Rutas de login:
from src.routes.Login_auth import auth_bp
# Sincronizacion de Podio a Postgre (datos antiguos):
from src.routes.podio_routes.sync_routes import sync_bp
# Revisión de registros
from src.routes.podio_routes.revision_route import sync_revision_bp
# Rutas de webhooks:
from src.routes.Webhook_bp import webhook_bp
from src.routes.podio_routes.AdminHooks import admin_bp
# Rutas de Quickbooks
from src.routes.qbo_routes.app_urls import qbo_bp
from src.quickbooks.qbo_auth import qbo_oauth_bp

# Test
from src.tests.debug_podio import debug_bp


def create_app():
    app = Flask(__name__)

    # Middleware de logs para todas las rutas
    register_request_logger(app)

    # Habilitar CORS
    CORS(app)

    # Registrar blueprints
    app.register_blueprint(attachments_bp)
    app.register_blueprint(change_order_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(client_manager_bp)
    app.register_blueprint(client_member_bp)
    app.register_blueprint(estimate_bp)
    app.register_blueprint(fdoc_item_bp)
    app.register_blueprint(fdocument_bp)
    app.register_blueprint(ftransaction_bp)
    app.register_blueprint(fdocument_ftransaction_bp)
    app.register_blueprint(job_bp)
    app.register_blueprint(job_multiplier_bp)
    app.register_blueprint(job_member_bp)
    app.register_blueprint(job_subcontractor_bp)
    app.register_blueprint(job_payment_unit_bp)
    app.register_blueprint(member_bp)
    app.register_blueprint(multiplier_bp)
    app.register_blueprint(opportunities_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(payment_unit_bp)
    app.register_blueprint(parent_mgmt_co_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(permission_bp)
    app.register_blueprint(permission_role_bp)
    app.register_blueprint(permission_member_bp)
    app.register_blueprint(permission_tech_bp)
    app.register_blueprint(purchase_bp)
    app.register_blueprint(purchase_order_bp)
    app.register_blueprint(purchase_order_item_bp)
    app.register_blueprint(purchase_supplier_bp)
    app.register_blueprint(role_bp)
    app.register_blueprint(skills_bp)
    app.register_blueprint(subcontractor_bp)
    app.register_blueprint(supplier_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(technician_bp)
    app.register_blueprint(tlactivity_bp)

    # Ruta para login
    app.register_blueprint(auth_bp)

    # RUTAS DE PODIO
    # Sincronización con Podio
    app.register_blueprint(sync_bp)
    # Revisión de registros ya migrados de Podio
    app.register_blueprint(sync_revision_bp)
    # Para recibir todos los webhooks
    app.register_blueprint(webhook_bp)
    # Para crear o eliminar los hooks de Podio
    app.register_blueprint(admin_bp)

    app.register_blueprint(debug_bp)  # test

    # Para conexión con Quickbooks
    app.register_blueprint(qbo_bp)
    app.register_blueprint(qbo_oauth_bp)  # Solo para conseguir los tokens

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
