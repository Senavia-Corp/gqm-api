from sqlmodel import select
from src.utils.id_generator import generate_custom_id
from src.utils.mappers.from_podio.subcontractor_mapper import map_podio_item_to_subc
from src.models.SubcontractorModel import Subcontractor
from src.utils.mappers.from_podio.subcontractor_skill_relationship import get_or_create_skill_by_dt, link_subc_skill
from src.utils.mappers.podio_value_extractor import get_podio_field_value
from src.podio.sync.sync_subcontractors import normalize_to_list


def upsert_subc_from_item(session, item):
    mapped = map_podio_item_to_subc(item)
    podio_item_id = mapped["podio_item_id"]

    existing = session.exec(
        select(Subcontractor).where(
            Subcontractor.podio_item_id == podio_item_id)
    ).first()

    if existing:
        target = existing

    else:
        new_id = generate_custom_id(
            session, Subcontractor, "ID_Subcontractor", "SUBC")
        mapped["ID_Subcontractor"] = new_id
        target = Subcontractor(**mapped)

    for k, v in mapped.items():
        if k != "ID_Subcontractor":
            setattr(target, k, v)

    session.add(target)
    return target


def add_subcontractor_skill_relations(session, subcontractor, item):
    fields = item.get("fields", [])

    division_trade = get_podio_field_value(
        fields=fields,
        field_ids="contractor-type"
    )

    division_trades = normalize_to_list(division_trade)

    for trade in division_trades:

        if not trade:
            continue

        clean_trade = trade.strip()

        skill = get_or_create_skill_by_dt(
            session=session,
            division_trade=clean_trade
        )

        link_subc_skill(
            session=session,
            subcon_id=subcontractor.ID_Subcontractor,
            skills_id=skill.ID_Skill
        )


# -------- FUNCIÓN PARA UNIFICAR SUBCONTRACTOR FASE 1 Y 2
def process_subcs_podio(session, item):

    subc = upsert_subc_from_item(session, item)

    add_subcontractor_skill_relations(session, subc, item)
