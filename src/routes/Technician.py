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
from ..utils.middleware.auth.routes_protection import require_permission
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

        if not obj:
            raise AppException("Technician not found", "not_found", 404)

        # Construir JSON limpio con la info del cliente
        technician_data = add_relationships(
            obj, ["subcontractor", "subcontractor.jobs", "tasks", "attachments", "permissions"])

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

        obj.Password = hash_password(obj.Password)  # Hash al password

        new_id = generate_custom_id(
            session, Technician, "ID_Technician", "TEC")
        obj.ID_Technician = new_id

        save_with_retry(session, obj)

        response = obj.model_dump()
        response.pop("Password", None)

        return jsonify(response), 201


# Ruta para actualizar un técnico
@technician_bp.patch("/<id_technician>")
@require_permission("technician:update")
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

        # Hash al passsword si se actualiza
        if "Password" in update_data_dict:
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
