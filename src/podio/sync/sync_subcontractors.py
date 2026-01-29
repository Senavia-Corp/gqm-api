from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.utils.id_generator import generate_custom_id
from src.podio.services.subcontractor_services import podio_subc_router
from src.utils.mappers.from_podio.subcontractor_mapper import map_podio_item_to_subc
from src.models.SubcontractorModel import Subcontractor


# ===============================
# ----------- FASE 1 -----------
# ===============================

# SYNC Subcontractors
@retry_db(max_retries=3, delay=1)
def sync_subc(limit: int = 30, offset: int = 0, dry_run: bool = False):
    """
    Sincronzación de Subcontractors desde Podio a PostgreSQL.
    - Batch pequeño
    - Offset manual
    - Dry-run opcional
    """

    service = podio_subc_router.get_service()
    items = service.get_items(limit=limit, offset=offset)

    print(f"📥 Subcontractors recibidos: {len(items)} | offset={offset}")

    if not items:
        print("✅ No hay más registros.")
        return {"processed": 0}

    created = 0
    updated = 0

    with get_session() as session:
        for item in items:
            mapped = map_podio_item_to_subc(item)
            podio_item_id = mapped["podio_item_id"]

            existing = session.exec(
                select(Subcontractor).where(
                    Subcontractor.podio_item_id == podio_item_id)
            ).first()

            if existing:
                changes = {
                    k: v for k, v in mapped.items()
                    if getattr(existing, k) != v
                }

                if changes:
                    updated += 1
                    if not dry_run:
                        for k, v in changes.items():
                            setattr(existing, k, v)

            else:
                created += 1
                if not dry_run:
                    new_id = generate_custom_id(
                        session, Subcontractor, "ID_Subcontractor", "SUBC"
                    )
                    mapped["ID_Subcontractor"] = new_id
                    session.add(Subcontractor(**mapped))

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "created": created,
        "updated": updated,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }
