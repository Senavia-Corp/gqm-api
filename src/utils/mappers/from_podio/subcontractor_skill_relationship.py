from sqlmodel import select
from src.utils.id_generator import generate_custom_id
from src.models.SkillsModel import Skills
from src.models.link_models.SkillsSubcontractor import SkillsSubcLink


# Obtener o crear skill (por Division Trade)
def get_or_create_skill_by_dt(
    session,
    division_trade: str
) -> Skills:
    """
    Busca una Skill por Division Trade (case-insensitive).
    Si no existe, lo crea.
    """
    clean_trade = division_trade.strip()

    skill = session.exec(
        select(Skills).where(
            Skills.Division_trade.ilike(clean_trade)
        )
    ).first()

    if skill:
        return skill

    new_id = generate_custom_id(
        session, Skills, "ID_Skill", "SKI"
    )

    skill = Skills(
        ID_Skill=new_id,
        Division_trade=clean_trade
    )

    session.add(skill)
    session.flush()  # importante para usar el ID luego

    return skill


# Crear link entre skill y subcontractor
def link_subc_skill(
    session,
    subcon_id: str,
    skills_id: str
):
    """
    Crea relación Subcontrator_Skill si no existe.
    """
    exists = session.exec(
        select(SkillsSubcLink).where(
            SkillsSubcLink.subcon_id == subcon_id,
            SkillsSubcLink.skills_id == skills_id,
        )
    ).first()

    if exists:
        return

    session.add(
        SkillsSubcLink(
            subcon_id=subcon_id,
            skills_id=skills_id,
        )
    )
