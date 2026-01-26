from flask import Blueprint, jsonify
from ...database.db_sqlmodel import get_session
from ...models.SkillsModel import Skills
from ...models.SubcontractorModel import Subcontractor
from ...models.link_models.SkillsSubcontractor import SkillsSubcLink


# ------------------- Link entre Skills y Subcontractor -------------------
skills_subcontractors_bp = Blueprint(
    "skills_subcontractors_blueprint", __name__, url_prefix="/skills_subcontractors")


# Vincular una skill con un subcontractor
@skills_subcontractors_bp.post("/skills/<skills_id>/subcontractors/<subcon_id>")
def assign_skill_to_subc(skills_id, subcon_id):
    with get_session() as session:
        skill = session.get(Skills, skills_id)
        subcontractor = session.get(Subcontractor, subcon_id)

        if not skill or not subcontractor:
            return jsonify({"error": "Skill or Subcontractor not found"}), 404

        existing_link = session.get(
            SkillsSubcLink, (skills_id, subcon_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = SkillsSubcLink(
            skills_id=skills_id,
            subcon_id=subcon_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "skills_id": skills_id,
            "subcon_id": subcon_id
        }), 201


# Desvincular una skill de un subcontractor
@skills_subcontractors_bp.delete("/skills/<skills_id>/subcontractors/<subcon_id>")
def remove_skill_from_subc(skills_id, subcon_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            SkillsSubcLink,
            (skills_id, subcon_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "skills_id": skills_id,
            "subcon_id": subcon_id
        }), 200
