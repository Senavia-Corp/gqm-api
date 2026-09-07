# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.TechnicianModel import Technician, TechnicianCreate, TechnicianUpdate
from ..models.SubcontractorModel import Subcontractor
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.auth.password_hashing import hash_password
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.auth.routes_protection import require_permission, self_profile_guard, portal_scope, portal_owns_technician
from ..utils.password_policy import validar_password, PasswordDebil
from ..utils.audit import audit
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException

# Blueprint de Technician:
technician_bp = Blueprint("technician_blueprint",
                          __name__, url_prefix="/technician")

# -------------------RUTAS CRUD-------------------#

# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los técnicos


@technician_bp.get("/")
@require_permission("technician:read")
@handle_exceptions()
@paginate()  # decorador de paginación
def list_technicians():
    with get_session() as session:
        statement = (
            select(Technician)
            .options(
                joinedload(Technician.subcontractor).joinedload(
                    Subcontractor.jobs),
                joinedload(Technician.tasks),
                joinedload(Technician.attachments),
                joinedload(Technician.permissions),
            )
        )

        # P-02: este listado devolvía TODOS los técnicos del sistema — la deuda
        # que el PR #116 marcó «sin scoping, Fase B». Decisión ratificada por el
        # cliente: un subcontratista ve SOLO los suyos y un técnico solo se ve a
        # sí mismo. El staff (full_admin, gqm_member) sigue sin filtro.
        # El filtro va en el statement y no sobre la lista ya construida porque
        # @paginate calcula `total` con lo que devolvemos: acotando antes, el
        # `total` cuenta solo los propios y no delata cuántos técnicos hay.
        rol_portal, uid_portal = portal_scope()
        if rol_portal == "subcontractor":
            statement = statement.where(
                Technician.ID_Subcontractor == uid_portal)
        elif rol_portal == "technician":
            statement = statement.where(
                Technician.ID_Technician == uid_portal)

        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        technician_data = []

        for tech in results:
            data = add_relationships(
                tech, ["subcontractor", "subcontractor.jobs", "tasks", "attachments", "permissions"])
            technician_data.append(data)

        return technician_data, 200


# Ruta para conseguir un técnico por ID_Technician
@technician_bp.get("/<id_technician>")
@require_permission("technician:read")
@handle_exceptions()
def get_tech_by_id(id_technician):
    with get_session() as session:
        statement = (
            select(Technician)
            .options(
                joinedload(Technician.subcontractor).joinedload(
                    Subcontractor.jobs),
                joinedload(Technician.tasks),
                joinedload(Technician.attachments),
                joinedload(Technician.permissions),
            )
            .where(Technician.ID_Technician == id_technician)
        )

        obj = session.exec(statement).unique().first()

        # P-01: esta ruta no comprobaba pertenencia, así que un subcontratista
        # leía la ficha de CUALQUIER técnico con sus tareas dentro — y con eso
        # rodeaba el scoping de /tasks/: sobre la MISMA tarea, GET /tasks/<id>
        # daba 404 y GET /technician/<id> la devolvía en 200.
        # 404 y no 403 a propósito (convención de esta base, Job.py:506-507):
        # un 403 confirmaría que el técnico existe y haría la ruta enumerable.
        # Mismo modismo que Tasks.py:170.
        if not obj or not portal_owns_technician(session, id_technician):
            raise AppException("Technician not found", "not_found", 404)

        # `permissions` SE MANTIENE en la expansión.
        #
        # Se quitó en el primer arreglo de F-01 y fue un error: es la fuente de
        # la pestaña Permissions del detalle de técnico del panel de
        # administración. Sin el campo, el contador queda a 0, la lista de chips
        # no se pinta, y con ella desaparece el ÚNICO botón del panel que revoca
        # un permiso a un técnico (DELETE /technician/<id>/permissions/<permId>).
        # Se rompió una pantalla del admin para cerrar algo que ya estaba
        # cerrado: la redacción central de portal_redaction.py borra `Document`
        # —la política en sí— para los roles de portal y se la deja entera al
        # staff. Verificado: el sub recibe {ID_Permission, Name, Description,
        # Active} sin `Document`; el full_admin lo recibe completo.
        technician_data = add_relationships(
            obj, ["subcontractor", "subcontractor.jobs", "tasks", "attachments",
                  "permissions"])

        return jsonify(technician_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un técnico
@technician_bp.post("/")
@require_permission("technician:create")
@handle_exceptions()
@audit("Technician created", entity_type="Technician", id_from="response")
def create_techician():
    data = request.get_json()
    create_techician = TechnicianCreate.model_validate(data)
    obj = Technician.model_validate(create_techician)

    with get_session() as session:

        # O-01: hasta ahora "1", "abc", "password" y "12345678" devolvían 201.
        # Se valida en SERVIDOR porque el alta la teclea un administrador: una
        # comprobación solo en el panel no protege de un curl ni del alta masiva
        # de los 432 subcontratistas. El hasheo no cambia.
        try:
            validar_password(obj.Password)
        except PasswordDebil as debil:
            raise AppException(str(debil), "weak_password", 400)

        obj.Password = hash_password(obj.Password)  # Hash al password

        new_id = generate_custom_id(
            session, Technician, "ID_Technician", "TEC")
        obj.ID_Technician = new_id

        save_with_retry(session, obj)

        response = obj.model_dump()
        response.pop("Password", None)

        # REG-142: bienvenida/alta (no bloqueante)
        try:
            from src.services.email_service import send_welcome
            if obj.Email_Address:
                send_welcome(obj.Email_Address, obj.Name or "there")
        except Exception:
            pass

        return jsonify(response), 201


# Ruta para actualizar un técnico
@technician_bp.patch("/<id_technician>")
@require_permission(["technician:update", "profile:update_own"])
@handle_exceptions()
@audit("Technician updated", entity_type="Technician", id_param="id_technician")
def update_technician(id_technician):
    data = request.get_json()
    with get_session() as session:
        obj = session.get(Technician, id_technician)
        if not obj:
            raise AppException("Technician not found", "not_found", 404)

        update_technician = TechnicianUpdate.model_validate(data)
        update_data_dict = update_technician.model_dump(
            exclude_unset=True)  # Crea dict limpio
        # Autoservicio: sin technician:update solo su propio registro,
        # sin campos privilegiados (Active/ID_Subcontractor).
        update_data_dict = self_profile_guard(
            "technician", id_technician, update_data_dict)

        # Hash al passsword si se actualiza
        if "Password" in update_data_dict:
            # O-01: misma política que en el alta. El cambio de contraseña por
            # PATCH era la otra puerta sin validar (incluida la del propio
            # técnico vía profile:update_own).
            try:
                validar_password(update_data_dict["Password"])
            except PasswordDebil as debil:
                raise AppException(str(debil), "weak_password", 400)
            update_data_dict["Password"] = hash_password(
                update_data_dict["Password"]
            )

        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        response = obj.model_dump()
        response.pop("Password", None)

        return jsonify(response), 200


# Ruta para eliminar un técnico
@technician_bp.delete("/<id_technician>")
@require_permission("technician:delete")
@handle_exceptions()
@audit("Technician deleted", entity_type="Technician", id_param="id_technician")
def delete_technician(id_technician):
    with get_session() as session:
        obj = session.get(Technician, id_technician)
        if not obj:
            raise AppException("Technician not found", "not_found", 404)

        delete_with_retry(session, obj)

        return jsonify({"message": f"Deleted Technician {id_technician}"}), 200
