from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.podio.services.pa_mgmt_co_services import podio_pa_mgmt_co_router
from src.utils.mappers.from_podio.parent_mgmt_co_mapper import map_podio_item_to_parent_mgmt_co
from src.models.ParentMgmtCoModel import ParentMgmtCo


# ===============================
# ----------- FASE 1 -----------
# ===============================

# SYNC Parent Mgmt Company
@retry_db(max_retries=3, delay=1)
def sync_parent_mgmt_company():
    """
    Sincroniza Parent Mgmt Company desde Podio a PostgreSQL.
    """
    print("\n🚀 Iniciando sincronización de Parent Mgmt Company")

    service = podio_pa_mgmt_co_router.get_service()

    limit = 10
    offset = 0
    total_processed = 0

    with get_session() as session:

        while True:
            print(f"🔁 Fetching Podio items: offset={offset}, limit={limit}")

            items = service.get_items(limit=limit, offset=offset)

            if not items:
                break

            print(f"📥 Items recibidos: {len(items)} (offset={offset})")

            for item in items:
                mapped = map_podio_item_to_parent_mgmt_co(item)

                podio_item_id = mapped.get("podio_item_id")
                tracking_id = mapped.get("ID_Community_Tracking")

                # -------------------------
                # Validaciones mínimas
                # -------------------------
                if not podio_item_id:
                    print("⚠️ Item sin podio_item_id, se omite")
                    continue

                if not tracking_id:
                    print(
                        f"❌ Item {podio_item_id} sin app_item_id_formatted, se omite"
                    )
                    continue

                # -------------------------
                # Buscar existente
                # -------------------------
                existing = session.exec(
                    select(ParentMgmtCo).where(
                        ParentMgmtCo.podio_item_id == podio_item_id
                    )
                ).first()

                if existing:
                    changes = {}

                    for field, new_value in mapped.items():
                        old_value = getattr(existing, field, None)
                        if new_value != old_value and new_value is not None:
                            changes[field] = new_value

                    if not changes:
                        print(
                            f"⚪ {existing.ID_Community_Tracking} — sin cambios"
                        )
                        continue

                    for field, value in changes.items():
                        setattr(existing, field, value)

                    print(
                        f"🟡 Actualizado {existing.ID_Community_Tracking} → {list(changes.keys())}"
                    )

                else:
                    try:
                        new_obj = ParentMgmtCo(**mapped)
                        session.add(new_obj)
                        print(
                            f"🟢 Insertado {mapped['ID_Community_Tracking']}"
                        )
                    except Exception as e:
                        print(
                            f"❌ Error insertando Parent Mgmt Co "
                            f"(podio_item_id={podio_item_id}): {e}"
                        )
                        continue

                total_processed += 1

            session.commit()
            offset += limit

    print(
        f"\n✅ Sincronización completa Parent Mgmt Company "
        f"(procesados={total_processed})"
    )
