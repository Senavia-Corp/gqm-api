from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.podio.services.job_services import podio_jobs_router
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from src.models.JobModel import Job


# ===============================
# ----------- FASE 1 -----------
# ===============================

# SYNC Jobs
@retry_db(max_retries=3, delay=1)
def sync_jobs(job_type: str, year: int, limit: int = 30, offset: int = 0, dry_run: bool = False):
    """
    Sincroniza Jobs desde Podio a PostgreSQL.
    """
    print(
        f"\n🚀 Sync Jobs | {job_type}-{year} "
        f"| limit={limit} offset={offset} dry_run={dry_run}"
    )

    service = podio_jobs_router.get_service(
        job_type=job_type,
        year=year
    )

    items = service.get_items(limit=limit, offset=offset)

    print(f"📥 Jobs recibidos: {len(items)} | offset={offset}")

    if not items:
        print("✅ No hay más registros.")
        return {"processed": 0}

    created = 0
    updated = 0

    with get_session() as session:
        for item in items:
            mapped = map_podio_item_to_job(item)

            podio_item_id = mapped.get("podio_item_id")
            tracking_id = mapped.get("ID_Jobs")

            # -------------------------
            # Validaciones mínimas
            # -------------------------
            if not podio_item_id or not tracking_id:
                print(
                    f"⚠️ Item inválido (podio_item_id={podio_item_id})"
                )
                continue

            existing = session.exec(
                select(Job).where(
                    Job.podio_item_id == podio_item_id
                )
            ).first()

            # -------------------------
            # UPDATE
            # -------------------------
            if existing:
                changes = {
                    k: v for k, v in mapped.items()
                    if getattr(existing, k) != v
                }

                if changes:
                    updated += 1
                    print(
                        f"🟡 Update {existing.ID_Jobs} → {list(changes.keys())}"
                    )

                    if not dry_run:
                        for k, v in changes.items():
                            setattr(existing, k, v)

                else:
                    print(f"⚪ {existing.ID_Jobs} — sin cambios")

            # -------------------------
            # INSERT
            # -------------------------
            else:
                created += 1
                print(f"🟢 Insert {mapped['ID_Jobs']}")

                if not dry_run:
                    session.add(Job(**mapped))

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "created": created,
        "updated": updated,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run,
        "job_type": job_type,
        "year": year
    }
