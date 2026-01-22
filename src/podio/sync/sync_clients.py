from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.utils.id_generator import generate_custom_id
from src.podio.services.client_services import podio_clients_router
from src.utils.mappers.from_podio.client_mapper import map_podio_item_to_client
from src.models.ClientModel import Client


# ===============================
# ----------- FASE 1 -----------
# ===============================

# SYNC Clients
@retry_db(max_retries=3, delay=1)
def sync_clients(limit: int = 30, offset: int = 0, dry_run: bool = False):
    """
    Sincronzación de Clients desde Podio a PostgreSQL.
    - Batch pequeño
    - Offset manual
    - Dry-run opcional
    """

    service = podio_clients_router.get_service()
    items = service.get_items(limit=limit, offset=offset)

    print(f"📥 Clients recibidos: {len(items)} | offset={offset}")

    if not items:
        print("✅ No hay más registros.")
        return {"processed": 0}

    created = 0
    updated = 0

    with get_session() as session:
        for item in items:
            mapped = map_podio_item_to_client(item)
            podio_item_id = mapped["podio_item_id"]

            existing = session.exec(
                select(Client).where(Client.podio_item_id == podio_item_id)
            ).first()

            if existing:
                changes = {
                    k: v for k, v in mapped.items()
                    if v is not None and getattr(existing, k) != v
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
                        session, Client, "ID_Client", "CLI"
                    )
                    mapped["ID_Client"] = new_id
                    session.add(Client(**mapped))

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
