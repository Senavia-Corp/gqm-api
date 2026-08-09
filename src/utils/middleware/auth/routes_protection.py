from functools import wraps
from flask import request, jsonify, g
from src.utils.middleware.auth.jwt_handler import decode_access_token

# Nuevas importancias para policy evaluator
from sqlmodel import select
from sqlalchemy.orm import joinedload
from src.database.db_sqlmodel import get_session
from src.utils.policy_evaluator import PolicyEvaluator
from src.models.MemberModel import Member
from src.models.RoleModel import Role
from src.models.TechnicianModel import Technician
from src.models.SubcontractorModel import Subcontractor


def get_user_context():
    """
    Extracts and returns (user_id, user_type, policies) from the JWT in the request.
    Returns (None, None, []) if there is no valid Authorization header or token.
    Does NOT block the request — callers decide what to do with the result.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, None, []

    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        return None, None, []

    user_id = payload.get("sub")
    user_type = payload.get("role")

    policies = []
    try:
        with get_session() as session:
            if user_type == "member":
                user = session.exec(
                    select(Member)
                    .options(
                        joinedload(Member.role).joinedload(Role.permissions),
                        joinedload(Member.permissions)
                    )
                    .where(Member.ID_Member == user_id)
                ).unique().first()

                if user:
                    policies.extend([p.Document for p in user.permissions if p.Active])
                    if user.role:
                        policies.extend([p.Document for p in user.role.permissions if p.Active])

            elif user_type == "technician":
                user = session.exec(
                    select(Technician)
                    .options(joinedload(Technician.permissions))
                    .where(Technician.ID_Technician == user_id)
                ).unique().first()

                if user:
                    policies.extend([p.Document for p in user.permissions if p.Active])

            elif user_type == "subcontractor":
                user = session.exec(
                    select(Subcontractor)
                    .options(
                        joinedload(Subcontractor.role).joinedload(Role.permissions),
                        joinedload(Subcontractor.permissions)
                    )
                    .where(Subcontractor.ID_Subcontractor == user_id)
                ).unique().first()

                if user:
                    policies.extend([p.Document for p in user.permissions if p.Active])
                    if user.role:
                        policies.extend([p.Document for p in user.role.permissions if p.Active])
    except Exception:
        pass

    return user_id, user_type, policies

def protect_blueprint(bp, resource: str, fixed_action: str | None = None,
                      overrides: dict | None = None):
    """Autorización por defecto para TODAS las rutas de un blueprint (REG-004).

    Convención de acciones (la misma de los @require_permission existentes):
    GET/HEAD → {resource}:read · POST → :create · PUT/PATCH → :update ·
    DELETE → :delete. `fixed_action` fuerza una única acción para todo el
    blueprint (p.ej. "iam:manage", "qbo:manage", "admin:sync"). `overrides`
    mapea nombre de view-function → acción (o None = sin chequeo extra).
    """

    def _authorize():
        if request.method == "OPTIONS":
            return None

        endpoint = (request.endpoint or "").split(".")[-1]
        if overrides and endpoint in overrides:
            action = overrides[endpoint]
            if action is None:
                return None
        elif fixed_action:
            action = fixed_action
        else:
            method = request.method.upper()
            if method in ("GET", "HEAD"):
                action = f"{resource}:read"
            elif method == "DELETE":
                action = f"{resource}:delete"
            elif method == "POST":
                action = f"{resource}:create"
            else:
                action = f"{resource}:update"

        user_id, user_type, policies = get_user_context()
        if not user_id:
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        if not PolicyEvaluator.evaluate(policies, action, "*"):
            return jsonify({"error": f"Forbidden: requiere permiso {action}"}), 403

        g.current_user = {"id": user_id, "role": user_type}
        return None

    bp.before_request(_authorize)
    return bp


def portal_scope():
    """(tipo, id) si el usuario autenticado es de portal (sub/técnico)."""
    user = getattr(g, "current_user", None) or {}
    role = user.get("role")
    if role in ("subcontractor", "technician"):
        return role, user.get("id")
    return None, None


def scope_jobs_statement(statement):
    """REG-037/110/111: los roles de portal solo ven SUS jobs asignados."""
    role, uid = portal_scope()
    if role == "subcontractor":
        from src.models.JobModel import Job
        from src.models.SubcontractorModel import Subcontractor
        return statement.where(
            Job.subcontractors.any(Subcontractor.ID_Subcontractor == uid))
    if role == "technician":
        from src.models.JobModel import Job
        from src.models.TechnicianModel import Technician
        return statement.where(
            Job.technicians.any(Technician.ID_Technician == uid))
    return statement


def require_role(*allowed_roles):
    """
    allowed_roles = lista de roles permitidos para la ruta.
    Ej:
        @require_role("member")
        @require_role("member", "technician")
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):

            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return jsonify({"error": "Missing or invalid Authorization header"}), 401

            token = auth_header.split(" ")[1]
            payload = decode_access_token(token)

            if not payload:
                return jsonify({"error": "Invalid or expired token"}), 401

            user_role = payload.get("role")

            # Si se especificaron roles, validar acceso
            if allowed_roles and user_role not in allowed_roles:
                return jsonify({"error": "Forbidden: insufficient permissions"}), 403

            # Guardar info del usuario autenticado
            g.current_user = {
                "id": payload.get("sub"),
                "role": user_role
            }

            return f(*args, **kwargs)

        return wrapper
    return decorator


def require_permission(actions: list | str, resource: str = "*"):
    """
    Evalúa si el usuario autenticado posee políticas JSON (IAM-style) 
    que le permitan ejecutar la 'action' requerida sobre el 'resource'.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Extraer payload del token si no ha sido extraido previamente (ejemplo, por @require_role)
            if hasattr(g, "current_user") and g.current_user:
                user_id = g.current_user["id"]
                user_type = g.current_user["role"]
            else:
                auth_header = request.headers.get("Authorization")
                if not auth_header or not auth_header.startswith("Bearer "):
                    return jsonify({"error": "Missing or invalid Authorization header"}), 401
                
                token = auth_header.split(" ")[1]
                payload = decode_access_token(token)
                
                if not payload:
                    return jsonify({"error": "Invalid or expired token"}), 401

                user_id = payload.get("sub")
                user_type = payload.get("role")
                
                g.current_user = {
                    "id": user_id,
                    "role": user_type
                }

            policies = []
            
            try:
                with get_session() as session:
                    if user_type == "member": # Evaluacion para miembros GQM
                        user = session.exec(
                            select(Member)
                            .options(
                                joinedload(Member.role).joinedload(Role.permissions), 
                                joinedload(Member.permissions)
                            )
                            .where(Member.ID_Member == user_id)
                        ).unique().first()
                        
                        if user:
                            # Inline policies (Directas al Miembro)
                            policies.extend([p.Document for p in user.permissions if p.Active])
                            # Role policies (Heredadas de su Rol)
                            if user.role:
                                policies.extend([p.Document for p in user.role.permissions if p.Active])
                                
                    elif user_type == "technician": # Evaluación para Sub-Contratistas 
                        user = session.exec(
                            select(Technician)
                            .options(joinedload(Technician.permissions))
                            .where(Technician.ID_Technician == user_id)
                        ).unique().first()
                        
                        if user:
                            policies.extend([p.Document for p in user.permissions if p.Active])

                    elif user_type == "subcontractor":
                        user = session.exec(
                            select(Subcontractor)
                            .options(
                                joinedload(Subcontractor.role).joinedload(Role.permissions),
                                joinedload(Subcontractor.permissions)
                            )
                            .where(Subcontractor.ID_Subcontractor == user_id)
                        ).unique().first()
                        
                        if user:
                            policies.extend([p.Document for p in user.permissions if p.Active])
                            if user.role:
                                policies.extend([p.Document for p in user.role.permissions if p.Active])
                            
            except Exception as e:
                print(f"Error checking DB permissions: {e}")
                return jsonify({"error": "Internal database error assessing permissions"}), 500
                
            # Llamamos a nuestro Evaluator utility para verificar las reglas completas
            g.user_policies = policies
            actions_list = [actions] if isinstance(actions, str) else actions
            has_permission = False
            for act in actions_list:
                if PolicyEvaluator.evaluate(policies, act, resource):
                    has_permission = True
                    break
            if not has_permission:
                return jsonify({"error": f"Forbidden: You do not have the required {actions_list} permission(s)"}), 403
                
            return f(*args, **kwargs)
        return wrapper
    return decorator
