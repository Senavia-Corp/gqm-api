# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.SkillsModel import Skills, SkillsCreate, SkillsUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.auth.routes_protection import require_permission
from ..utils.audit import audit
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException


# Blueprint de Skill:
skills_bp = Blueprint("skills_blueprint", __name__, url_prefix="/skills")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todas las habilidades
@skills_bp.get("/")
@require_permission("skill:read")
@handle_exceptions()
@paginate(default_limit=200, max_limit=1000)  # Aumentar límite para filtros
def list_skills():
    with get_session() as session:
        # Seleccionar solo lo necesario para el dropdown
        statement = select(Skills)
        results = session.exec(statement).all()

        if not results:
            return [], 200

        # Solo serializar campos base (ID y Nombre)
        skills_data = [
            {
                "ID_Skill": skill.ID_Skill,
                "Skill_name": skill.Skill_name,
                "Division_trade": skill.Division_trade
            }
            for skill in results
        ]

        return skills_data, 200


# Ruta para conseguir una habilidad por ID_Skills
@skills_bp.get("/<id_skill>")
@require_permission("skill:read")
@handle_exceptions()
def get_skill_by_id(id_skill):
    with get_session() as session:
        statement = (
            select(Skills)
            .options(
                joinedload(Skills.subcontractors),
                joinedload(Skills.opportunities)
            )
            .where(Skills.ID_Skill == id_skill)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Skill not found", "not_found", 404)

        # Construir JSON limpio con la info
        skill_data = add_relationships(
            obj, ["subcontractors", "opportunities"])

        return jsonify(skill_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una habilidad
@skills_bp.post("/")
@require_permission("skill:create")
@handle_exceptions()
@audit("Skill created", entity_type="Skill", id_from="response")
def create_skill():
    data = request.get_json()
    create_skill = SkillsCreate.model_validate(data)
    obj = Skills.model_validate(create_skill)

    with get_session() as session:
        new_id = generate_custom_id(
            session, Skills, "ID_Skill", "SKI")
        obj.ID_Skill = new_id

        save_with_retry(session, obj)

        return jsonify(obj.model_dump()), 201


# Ruta para actualizar una habilidad
@skills_bp.patch("/<id_skill>")
@require_permission("skill:update")
@handle_exceptions()
@audit("Skill updated", entity_type="Skill", id_param="id_skill")
def update_skill(id_skill):
    data = request.get_json()
    with get_session() as session:
        obj = session.get(Skills, id_skill)
        if not obj:
            raise AppException("Skill not found", "not_found", 404)

        update_skill = SkillsUpdate.model_validate(data)
        update_data_dict = update_skill.model_dump(
            exclude_unset=True)  # Crea dict limpio

        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar una habilidad
@skills_bp.delete("/<id_skill>")
@require_permission("skill:delete")
@handle_exceptions()
@audit("Skill deleted", entity_type="Skill", id_param="id_skill")
def delete_skill(id_skill):
    with get_session() as session:
        obj = session.get(Skills, id_skill)
        if not obj:
            raise AppException("Skill not found", "not_found", 404)

        delete_with_retry(session, obj)

        return jsonify({"message": f"Deleted Skill {id_skill}"}), 200
