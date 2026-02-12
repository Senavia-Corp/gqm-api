from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.podio.services.bldg_dept_services import podio_bldg_dept_router
from src.utils.mappers.from_podio.bldg_dept_mapper import map_podio_item_to_bldg_dept
from src.models.BldgDeptModel import BuildingDept


# ===============================
# ----------- FASE 1 -----------
# ===============================

# SYNC Building Department
@retry_db(max_retries=3, delay=1)
def sync_bldg_dept():
    """
    Sincroniza Building Department desde Podio a PostgreSQL.
    """
    print("\n🚀 Iniciando sincronización de Building Department")

    service = podio_bldg_dept_router.get_service()

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
                mapped = map_podio_item_to_bldg_dept(item)

                podio_item_id = mapped.get("podio_item_id")
                tracking_id = mapped.get("ID_BldgDept")

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
                    select(BuildingDept).where(
                        BuildingDept.podio_item_id == podio_item_id
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
                            f"⚪ {existing.ID_BldgDept} — sin cambios"
                        )
                        continue

                    for field, value in changes.items():
                        setattr(existing, field, value)

                    print(
                        f"🟡 Actualizado {existing.ID_BldgDept} → {list(changes.keys())}"
                    )

                else:
                    try:
                        new_obj = BuildingDept(**mapped)
                        session.add(new_obj)
                        print(
                            f"🟢 Insertado {mapped['ID_BldgDept']}"
                        )
                    except Exception as e:
                        print(
                            f"❌ Error insertando Building Department"
                            f"(podio_item_id={podio_item_id}): {e}"
                        )
                        continue

                total_processed += 1

            session.commit()
            offset += limit

    print(
        f"\n✅ Sincronización completa Building Department"
        f"(procesados={total_processed})"
    )
