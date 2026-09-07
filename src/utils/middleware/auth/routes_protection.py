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


# Campos que el autoservicio de perfil NUNCA puede tocar (escalada REG-006).
#
# P-08 (auditoria de portal): esta lista filtraba `Active`, y `Subcontractor` NO
# TIENE columna `Active` — tiene `Status`. El resultado medido: un subcontratista
# se ponia a si mismo `Gqm_compliance='APROBADO-POR-MI-MISMO'` y `Score=99.0` via
# `profile:update_own`, y la fila quedaba escrita. Se autoaprobaba el
# cumplimiento con el que GQM decide a quien asigna trabajo.
#
# Se anaden los cuatro campos que gobiernan esa evaluacion. `Active` se conserva
# porque `Member` y `Technician` si la tienen.
PROFILE_PRIVILEGED_FIELDS = {
    "ID_Role", "Active", "ID_Subcontractor",
    "Status", "Score", "Gqm_compliance", "Gqm_best_service_training",
}


def self_profile_guard(target_type: str, target_id: str, update_data: dict) -> dict:
    """Autoservicio de perfil (hallazgo ALTO del review final): quien no tiene
    el permiso {target_type}:update solo entra por profile:update_own — se
    exige que el target sea su PROPIO registro y se filtran los campos
    privilegiados. Con el permiso pleno, pasa intacto."""
    from src.utils.middleware.exceptions_handler import AppException

    policies = getattr(g, "user_policies", []) or []
    if PolicyEvaluator.evaluate(policies, f"{target_type}:update", "*"):
        return update_data

    user = getattr(g, "current_user", None) or {}
    if user.get("role") != target_type or user.get("id") != target_id:
        raise AppException(
            "Forbidden: solo puedes editar tu propio perfil.", "forbidden", 403)
    return {k: v for k, v in update_data.items()
            if k not in PROFILE_PRIVILEGED_FIELDS}


def portal_owns_technician(session, id_technician: str) -> bool:
    """Pertenencia de un tecnico respecto del llamante.

    Bloque A de la auditoria de portal. Reglas ratificadas por el cliente
    (ambiguedad 1): un subcontratista solo alcanza a SUS tecnicos; un tecnico,
    solo a si mismo. El staff pasa siempre.

    Un id inexistente devuelve False, para que el llamador responda 404 y no
    distinga «no existe» de «no es tuyo»: es la convencion de esta base de
    codigo (Job.py:506-507) y evita que la ruta sea enumerable.
    """
    from src.models.TechnicianModel import Technician

    rol, uid = portal_scope()
    if rol is None:
        return True
    if rol == "technician":
        return id_technician == uid
    tecnico = session.get(Technician, id_technician)
    return tecnico is not None and tecnico.ID_Subcontractor == uid


def portal_owns_subcontractor(id_subcontractor: str) -> bool:
    """Pertenencia de un subcontratista respecto del llamante.

    Ambiguedad 5 ratificada: un sub no ve NADA de otro sub. Un tecnico no
    alcanza fichas de subcontratista (su politica no trae `subcontractor:read`,
    asi que el decorador ya corta antes; esto es la segunda linea).
    """
    rol, uid = portal_scope()
    if rol is None:
        return True
    if rol == "subcontractor":
        return id_subcontractor == uid
    return False


def scope_tasks_statement(statement):
    """REG (cobertura B7): los roles de portal solo ven SUS tareas —
    técnico: las asignadas a él; subcontratista: las suyas directas o las de
    sus jobs. Staff pasa sin filtro."""
    role, uid = portal_scope()
    if role is None:
        return statement

    from sqlalchemy import or_ as sa_or
    from sqlmodel import select as sq_select

    from src.models.TasksModel import Tasks
    from src.models.link_models.JobSubcontractor import JobSubcontractorLink

    from sqlalchemy import and_ as sa_and

    if role == "technician":
        return statement.where(Tasks.ID_Technician == uid)

    # El listado dice EXACTAMENTE lo mismo que `task_belongs_to_portal_user`:
    # las tuyas por dueno explicito, mas las de tus jobs QUE NO TENGAN DUENO.
    # Sin la segunda condicion, en una obra compartida el listado del sub A
    # incluia las tareas del sub B — y una divergencia entre el listado y la
    # comprobacion por id es justo el hueco por el que se cuelan los IDOR.
    return statement.where(sa_or(
        Tasks.ID_Subcontractor == uid,
        sa_and(
            Tasks.ID_Subcontractor.is_(None),
            Tasks.ID_Jobs.in_(
                sq_select(JobSubcontractorLink.job_id).where(
                    JobSubcontractorLink.subcontr_id == uid)),
        ),
    ))


def job_belongs_to_portal_user(session, job_id) -> bool:
    """True si el job está dentro del alcance del portal actual (staff siempre).

    Reutiliza `scope_jobs_statement` para no duplicar la lógica de alcance.
    """
    role, _ = portal_scope()
    if role is None or not job_id:
        return True

    from sqlmodel import select as sq_select

    from src.models.JobModel import Job

    stmt = scope_jobs_statement(sq_select(Job).where(Job.ID_Jobs == job_id))
    return session.exec(stmt).first() is not None


def task_belongs_to_portal_user(session, task) -> bool:
    """True si el usuario actual puede operar sobre la task (staff siempre)."""
    role, uid = portal_scope()
    if role is None:
        return True

    from sqlmodel import select as sq_select

    from src.models.link_models.JobSubcontractor import JobSubcontractorLink

    if role == "technician":
        return task.ID_Technician == uid

    dueno = getattr(task, "ID_Subcontractor", None)
    if dueno == uid:
        return True

    # Una tarea con dueno EXPLICITO que no eres tu no es tuya, aunque cuelgue de
    # un job que compartis.
    #
    # Antes bastaba con que la tarea estuviera en uno de tus jobs. En una obra
    # COMPARTIDA entre dos subcontratistas eso significaba que el sub A leia la
    # tarea del sub B —con el correo de su tecnico dentro— y ademas la
    # REESCRIBIA: medido, `PATCH /tasks/<tarea de B>` devolvia 200 y la fila
    # quedaba con el estado que puso A. Decision ratificada (ambiguedad 5): un
    # sub no ve NADA de otro sub.
    #
    # Las tareas SIN dueno de tus jobs siguen siendo tuyas: es el caso legitimo
    # de la tarea que el admin deja sin asignar para que la recoja quien pueda.
    if dueno is not None:
        return False

    if not task.ID_Jobs:
        return False
    return session.exec(sq_select(JobSubcontractorLink).where(
        JobSubcontractorLink.job_id == task.ID_Jobs,
        JobSubcontractorLink.subcontr_id == uid,
    )).first() is not None
