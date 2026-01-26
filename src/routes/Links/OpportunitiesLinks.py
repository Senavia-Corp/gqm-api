from flask import Blueprint, jsonify
from ...database.db_sqlmodel import get_session
from ...models.OpportunitiesModel import Opportunities
from ...models.SkillsModel import Skills
from ...models.SubcontractorModel import Subcontractor
from ...models.link_models.OpportunitiesLinks import OpportSkillsLink, OpportSubcLink


# ------------------- Link entre Opportunities y Skills -------------------
opportunities_skills_bp = Blueprint(
    "opportunities_skills_blueprint", __name__, url_prefix="/opportunities_skills")


# Vincular un opportunity con un skill
@opportunities_skills_bp.post("/opportunities/<opport_id>/skills/<skills_id>")
def assign_opportunity_to_skill(opport_id, skills_id):
    with get_session() as session:
        opportunity = session.get(Opportunities, opport_id)
        skill = session.get(Skills, skills_id)

        if not opportunity or not skill:
            return jsonify({"error": "Opportunity or Skills not found"}), 404

        existing_link = session.get(
            OpportSkillsLink, (opport_id, skills_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = OpportSkillsLink(
            opport_id=opport_id,
            skills_id=skills_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "opport_id": opport_id,
            "skills_id": skills_id
        }), 201


# Desvincular un opportunity de un skill
@opportunities_skills_bp.delete("/opportunities/<opport_id>/skills/<skills_id>")
def remove_opportunity_from_skill(opport_id, skills_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            OpportSkillsLink,
            (opport_id, skills_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "opport_id": opport_id,
            "skills_id": skills_id
        }), 200


# ------------------- Link entre Opportunities y Subcontractor -------------------
opportunities_subcontractors_bp = Blueprint(
    "opportunities_subcontractors_blueprint", __name__, url_prefix="/opportunities_subcontractors")


# Vincular un opportunity con un subcontractor
@opportunities_subcontractors_bp.post("/opportunities/<opport_id>/subcontractors/<subcon_id>")
def assign_opportunity_to_subc(opport_id, subcon_id):
    with get_session() as session:
        opportunity = session.get(Opportunities, opport_id)
        subcontractor = session.get(Subcontractor, subcon_id)

        if not opportunity or not subcontractor:
            return jsonify({"error": "Opportunity or Subcontractor not found"}), 404

        existing_link = session.get(
            OpportSubcLink, (opport_id, subcon_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = OpportSubcLink(
            opport_id=opport_id,
            subcon_id=subcon_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "opport_id": opport_id,
            "subcon_id": subcon_id
        }), 201


# Desvincular un opportunity de un subcontractor
@opportunities_subcontractors_bp.delete("/opportunities/<opport_id>/subcontractors/<subcon_id>")
def remove_opportunity_from_subc(opport_id, subcon_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            OpportSubcLink,
            (opport_id, subcon_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "opport_id": opport_id,
            "subcon_id": subcon_id
        }), 200
