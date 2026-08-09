from sqlmodel import select
from flask import Blueprint, jsonify, request
from ...database.db_sqlmodel import get_session
from ...models.SkillsModel import Skills
from ...models.SubcontractorModel import Subcontractor
from ...models.link_models.SkillsSubcontractor import SkillsSubcLink
from ...podio.services.subcontractor_services import podio_subc_router
from src.utils.mappers.convert_value_podio import convert_value_for_podio
from src.utils.mappers.mapper_aux_functions import register_event
from src.utils.audit import actor_member_id, log_activity, SOURCE_APP


# ------------------- Link entre Skills y Subcontractor -------------------
skills_subcontractors_bp = Blueprint(
    "skills_subcontractors_blueprint", __name__, url_prefix="/skills_subcontractors")


# Vincular una skill con un subcontractor
@skills_subcontractors_bp.post("/skills/<skills_id>/subcontractors/<subcon_id>")
def assign_skill_to_subc(subcon_id, skills_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:
        skill = session.get(Skills, skills_id)
        subcontractor = session.get(Subcontractor, subcon_id)

        if not skill or not subcontractor:
            return jsonify({"error": "Skill or Subcontractor not found"}), 404

        existing_link = session.get(
            SkillsSubcLink, (subcon_id, skills_id))

        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        # ----------- 🔵 CREAR EN DB
        link = SkillsSubcLink(
            subcon_id=subcon_id,
            skills_id=skills_id

        )

        session.add(link)

        member_id_header = actor_member_id()
        log_activity(
            session,
            action="Skill linked to Subcontractor",
            entity_id=subcon_id,
            entity_type="Subcontractor",
            member_id=member_id_header,
            description=f"Skill: {skill.Division_trade or skill.Skill_name or skills_id}",
            source=SOURCE_APP,
        )

        session.commit()

        # ----------- 🟢 CREAR EN PODIO (🔄 Enviar PATCH)
        if sync_podio:
            if subcontractor.podio_item_id:

                podio_service = podio_subc_router.get_service()

                # 🔎 1️⃣ Buscar todas las skills actuales del subcontractor
                skills_links = (
                    session.exec(
                        select(Skills)
                        .join(SkillsSubcLink,
                              Skills.ID_Skill == SkillsSubcLink.skills_id)
                        .where(SkillsSubcLink.subcon_id == subcon_id)
                    )
                    .all()
                )

                # 🧠 2️⃣ Armar lista de categorías
                division_trades = [
                    skill.Division_trade
                    for skill in skills_links
                    if skill.Division_trade
                ]

                # 🔄 3️⃣ Enviar lista completa a Podio
                podio_service.update_item(
                    int(subcontractor.podio_item_id),
                    {
                        "contractor-type": division_trades
                    }
                )

                register_event(subcontractor.podio_item_id)

        return jsonify({
            "status": "Linked 🔗",
            "skills_id": skills_id,
            "subcon_id": subcon_id
        }), 201


# Desvincular una skill de un subcontractor
@skills_subcontractors_bp.delete("/skills/<skills_id>/subcontractors/<subcon_id>")
def remove_skill_from_subc(subcon_id, skills_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            SkillsSubcLink,
            (subcon_id, skills_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        # ----------- 🔴 BORRAR EN DB
        skill = session.get(Skills, skills_id)
        session.delete(link)

        member_id_header = actor_member_id()
        log_activity(
            session,
            action="Skill unlinked from Subcontractor",
            entity_id=subcon_id,
            entity_type="Subcontractor",
            member_id=member_id_header,
            description=f"Skill: {skill.Division_trade or skill.Skill_name or skills_id}" if skill else f"Skill: {skills_id}",
            source=SOURCE_APP,
        )

        session.commit()

        subcontractor = session.get(Subcontractor, subcon_id)

        # ----------- 🟢 DELETE EN PODIO (🔄 Enviar PATCH)
        if sync_podio and subcontractor and subcontractor.podio_item_id:

            podio_service = podio_subc_router.get_service()

            # 🔎 Buscar skills restantes
            remaining_skills = (
                session.exec(
                    select(Skills)
                    .join(SkillsSubcLink,
                          Skills.ID_Skill == SkillsSubcLink.skills_id)
                    .where(SkillsSubcLink.subcon_id == subcon_id)
                )
                .all()
            )

            # 🧠 Armar lista nueva
            division_trades = [
                skill.Division_trade
                for skill in remaining_skills
                if skill.Division_trade
            ]

            # 🔄 Mandar lista completa (si no hay → [])
            podio_service.update_item(
                int(subcontractor.podio_item_id),
                {
                    "contractor-type": division_trades
                }
            )

            register_event(subcontractor.podio_item_id)

        return jsonify({
            "status": "Unlinked ✖️",
            "skills_id": skills_id,
            "subcon_id": subcon_id
        }), 200
