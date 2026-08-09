from src.config import PUBLIC_URL
from flask import Flask
from flask_cors import CORS
import sys
# Middleware de logs para todos los request:
from src.utils.middleware.logs.request_logger import register_request_logger
# Blueprints:
from src.routes.Job import job_bp, job_excel_bp
from src.routes.Links.JobLinks import job_member_bp, job_multiplier_bp, job_subcontractor_bp, job_payment_unit_bp, job_technician_bp
from src.routes.Client import client_bp
from src.routes.Subcontractor import subcontractor_bp
from src.routes.Supplier import supplier_bp
from src.routes.Tasks import tasks_bp
from src.routes.Member import member_bp
from src.routes.Technician import technician_bp
from src.routes.Skills import skills_bp
from src.routes.Links.SkillSubcLink import skills_subcontractors_bp
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
from src.routes.Links.OpportunitiesLinks import opportunities_skills_bp, opportunities_subcontractors_bp
from src.routes.TLActivity import tlactivity_bp
from src.routes.FinancialDocItem import fdoc_item_bp
from src.routes.FinancialDocument import fdocument_bp
from src.routes.FinancialTransaction import ftransaction_bp
from src.routes.Links.FinancialLinks import fdocument_ftransaction_bp
from src.routes.Purchase import purchase_bp
from src.routes.PurchaseOrder import purchase_order_bp
from src.routes.PurchaseOrderItem import purchase_order_item_bp
from src.routes.Links.PurchaseSupplierLink import purchase_supplier_bp
from src.routes.StandardPS import standard_ps_bp
from src.routes.BuildingDepartment import bldg_dept_bp
from src.routes.ChatMessage import chat_bp
from src.routes.Commission import commission_bp
from src.routes.CommissionGroup import commission_group_bp
from src.routes.CommissionDetail import commission_detail_bp
from src.routes.GQMInventory import inventory_bp
from src.routes.Reimbursement import reimbursement_bp
from src.routes.Certificate import certificate_bp
# Rutas de login:
from src.routes.Login_auth import auth_bp
# Sincronizacion de Podio a Postgre (datos antiguos):
from src.routes.podio_routes.sync_routes import sync_phase1_bp, sync_phase2_bp
# Revisión de registros traidos de Podio
from src.routes.podio_routes.revision_route import sync_revision_bp
# Ruta para pedir los user id de Podio
from src.podio.get_user_id import podio_filter_bp
# Rutas de webhooks:
from src.routes.Webhook_bp import webhook_bp
from src.routes.podio_routes.AdminHooks import admin_bp
# Rutas de Quickbooks
from src.routes.qbo_routes.app_urls import qbo_bp
from src.quickbooks.qbo_auth import qbo_oauth_bp
# Rutas de métricas
from src.services.metrics.aux_func_metrics import metrics_bp
from src.routes.financial_routes.financial_metrics_bp import financial_metrics_bp
from src.routes.timeline_metrics_bp import timeline_metrics_bp
from src.routes.financial_routes.FinancialJobReports import financial_jobs_bp
from src.routes.Dashboard.CommunitiesM import communities_bp
from src.routes.Dashboard.JobsM import job_metrics_bp
from src.routes.Dashboard.MembersM import member_metrics_bp
from src.routes.Dashboard.SubcontractorsM import subcontractor_metrics_bp

# Test
from src.tests.debug_podio import debug_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False  # Accept URLs with or without trailing slash (prevents 308 redirect that strips Authorization header)

    import os

    # REG-007: sin secret_key la sesión de Flask es NullSession y el flujo
    # OAuth de QBO (/qbo/connect ↔ /callback con state anti-CSRF) revienta.
    from decouple import config as _env
    secret_key = _env("SECRET_KEY", default=None)
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY es obligatoria (sesión Flask para el state de QBO OAuth)")
    app.secret_key = secret_key
    # Orígenes permitidos por defecto para desarrollo
    allowed_origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]
    
    # Orígenes desde variables de entorno (separados por coma)
    env_origins = os.environ.get("ALLOWED_ORIGINS")
    if env_origins:
        allowed_origins.extend([o.strip() for o in env_origins.split(",") if o.strip()])

    # Configurar CORS con origines específicos
    CORS(app, resources={r"/*": {"origins": allowed_origins}}, supports_credentials=True)
    # Middleware de logs para todas las rutas
    register_request_logger(app)

    @app.before_request
    def global_auth_middleware():
        from flask import request, jsonify, g
        from src.utils.middleware.auth.jwt_handler import decode_access_token

        # Ignorar peticiones OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return None

        # Whitelist de rutas públicas (REG-019/032/096): SOLO receptores de
        # webhooks (con su propia validación de token/firma), el retorno
        # OAuth de QBO (state anti-CSRF) y el ciclo de login/reset.
        # Fuera: /qbo/connect (solo Full Admin), /admin/hooks (muerta),
        # /sync, /podio (exponía el dump de debug), /test, /debug y
        # /webhook/podio/failed_syncs (gestión, no receptor).
        public_prefixes = [
            "/auth/login",
            "/auth/refresh",
            "/auth/forgot-password",
            "/auth/reset-password",
            "/webhook/podio/jobs",
            "/webhook/podio/others",
            "/webhook/qbo",
            "/callback",
        ]

        # Permitir root
        if request.path == "/":
            return None

        # Verificar si la ruta empieza con algún prefijo público
        for prefix in public_prefixes:
            if request.path.startswith(prefix):
                return None

        # Si no es pública, EXIGIR autenticación (Fail-Closed)
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Global Auth: Missing or invalid Authorization header"}), 401
            
        token = auth_header.split(" ")[1]
        payload = decode_access_token(token)
        
        if not payload:
            return jsonify({"error": "Global Auth: Invalid or expired token"}), 401
            
        # Almacenar datos en flask.g para que @require_permission no tenga que decodificarlos nuevamente
        g.current_user = {
            "id": payload.get("sub"),
            "role": payload.get("role")
        }

    # ── RBAC por blueprint (REG-004/REG-006/REG-020) ──────────────────────
    # Autorización por defecto para los blueprints que estaban SIN guard
    # (~190 endpoints). Convención: {resource}:{read|create|update|delete}.
    # Los archivos que ya traían @require_permission conservan sus decoradores.
    from src.utils.middleware.auth.routes_protection import protect_blueprint

    # Gestión IAM = solo Full Admin (REG-006: aquí estaba la escalada)
    for _bp in (permission_role_bp, permission_member_bp, permission_tech_bp):
        protect_blueprint(_bp, "iam", fixed_action="iam:manage")

    # QBO = solo Full Admin (decisión confirmada)
    protect_blueprint(qbo_bp, "qbo", fixed_action="qbo:manage")

    # Sync/administración Podio
    for _bp in (sync_phase1_bp, sync_phase2_bp, admin_bp):
        protect_blueprint(_bp, "admin", fixed_action="admin:sync")

    # Financiero
    for _bp in (order_bp, change_order_bp, estimate_bp, purchase_order_bp,
                purchase_order_item_bp, reimbursement_bp, fdocument_bp,
                purchase_supplier_bp, financial_metrics_bp, financial_jobs_bp,
                fdocument_ftransaction_bp):
        protect_blueprint(_bp, "finance")

    # Comisiones (archivos sin decoradores propios)
    for _bp in (commission_group_bp, commission_detail_bp):
        protect_blueprint(_bp, "commission")

    # Catálogos
    for _bp in (bldg_dept_bp, manager_bp, supplier_bp, standard_ps_bp,
                inventory_bp, multiplier_bp, payment_unit_bp):
        protect_blueprint(_bp, "catalog")

    # Links de Job
    for _bp in (job_member_bp, job_multiplier_bp, job_subcontractor_bp,
                job_payment_unit_bp, job_technician_bp):
        protect_blueprint(_bp, "job")

    # Clientes / oportunidades
    for _bp in (opportunities_bp, client_manager_bp, client_member_bp,
                opportunities_skills_bp, opportunities_subcontractors_bp):
        protect_blueprint(_bp, "client")

    # Links de skills (dispara escritura a Podio con sync_podio=true)
    protect_blueprint(skills_subcontractors_bp, "catalog")

    # Sync de revisión Podio: escritura arbitraria en BD → solo admin
    protect_blueprint(sync_revision_bp, "admin", fixed_action="admin:sync")

    # Reportes PDF de métricas
    protect_blueprint(metrics_bp, "dashboard")

    # Actividad (timeline de tareas)
    protect_blueprint(tlactivity_bp, "tasks")

    # Dashboards / métricas (solo lectura en la práctica)
    for _bp in (job_metrics_bp, member_metrics_bp, subcontractor_metrics_bp,
                communities_bp, timeline_metrics_bp, podio_filter_bp):
        protect_blueprint(_bp, "dashboard")

    # Registrar blueprints
    app.register_blueprint(attachments_bp)
    app.register_blueprint(bldg_dept_bp)
    app.register_blueprint(certificate_bp)
    app.register_blueprint(change_order_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(client_manager_bp)
    app.register_blueprint(client_member_bp)
    app.register_blueprint(commission_bp)
    app.register_blueprint(commission_group_bp)
    app.register_blueprint(commission_detail_bp)
    app.register_blueprint(estimate_bp)
    app.register_blueprint(fdoc_item_bp)
    app.register_blueprint(fdocument_bp)
    app.register_blueprint(ftransaction_bp)
    app.register_blueprint(fdocument_ftransaction_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(job_bp)
    app.register_blueprint(job_excel_bp)
    app.register_blueprint(job_multiplier_bp)
    app.register_blueprint(job_member_bp)
    app.register_blueprint(job_subcontractor_bp)
    app.register_blueprint(job_technician_bp)
    app.register_blueprint(job_payment_unit_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(member_bp)
    app.register_blueprint(multiplier_bp)
    app.register_blueprint(opportunities_bp)
    app.register_blueprint(opportunities_skills_bp)
    app.register_blueprint(opportunities_subcontractors_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(payment_unit_bp)
    app.register_blueprint(parent_mgmt_co_bp)
    app.register_blueprint(permission_bp)
    app.register_blueprint(permission_role_bp)
    app.register_blueprint(permission_member_bp)
    app.register_blueprint(permission_tech_bp)
    app.register_blueprint(purchase_bp)
    app.register_blueprint(purchase_order_bp)
    app.register_blueprint(purchase_order_item_bp)
    app.register_blueprint(purchase_supplier_bp)
    app.register_blueprint(reimbursement_bp)
    app.register_blueprint(role_bp)
    app.register_blueprint(skills_bp)
    app.register_blueprint(skills_subcontractors_bp)
    app.register_blueprint(standard_ps_bp)
    app.register_blueprint(subcontractor_bp)
    app.register_blueprint(supplier_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(technician_bp)
    app.register_blueprint(tlactivity_bp)

    # Ruta para login
    app.register_blueprint(auth_bp)

    # RUTAS DE PODIO
    # Sincronización con Podio
    app.register_blueprint(sync_phase1_bp)
    app.register_blueprint(sync_phase2_bp)
    # Revisión de registros ya migrados de Podio
    app.register_blueprint(sync_revision_bp)
    # Pedido de los user id de Podio
    app.register_blueprint(podio_filter_bp)
    # Para recibir todos los webhooks
    app.register_blueprint(webhook_bp)
    # Para crear o eliminar los hooks de Podio
    app.register_blueprint(admin_bp)

    # debug_bp expone items de Podio: SOLO en entorno de pruebas (REG-032/082)
    if _env("APP_ENV", default="production") == "test":
        app.register_blueprint(debug_bp)

    # Para conexión con Quickbooks
    app.register_blueprint(qbo_bp)
    app.register_blueprint(qbo_oauth_bp)  # Solo para conseguir los tokens

    # Rutas de métricas
    app.register_blueprint(metrics_bp)  # Para generar el pdf de Jobs
    # Para generar el pdf de financials de QBO
    app.register_blueprint(financial_metrics_bp)
    app.register_blueprint(timeline_metrics_bp)
    # Para generar el pdf de financials basadas en Jobs
    app.register_blueprint(financial_jobs_bp)
    # Para el dashboard de Client y Parent Co.
    app.register_blueprint(communities_bp)
    app.register_blueprint(job_metrics_bp)  # Para el dashboard
    app.register_blueprint(member_metrics_bp)
    # Para el dashboard de Subcontractors
    app.register_blueprint(subcontractor_metrics_bp)

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

        app.run(debug=True, host="0.0.0.0", port=80)

    except RuntimeError as e:
        print(f"\n[ERROR CRÍTICO] La aplicación no pudo iniciar: {e}")
        # Para terminar la ejecución de un programa inmediatamente, indicando que fue por un error
        sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR FATAL] Fallo inesperado al iniciar: {e}")
        sys.exit(1)
