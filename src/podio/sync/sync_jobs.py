from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.podio.services.job_services import podio_jobs_router
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from src.models.JobModel import Job
from src.utils.validators.jobs_validator import validate_batch_jobs
from src.utils.mappers.podio_relationships import get_related_app_ids, get_contact_profile_ids
from src.utils.mappers.from_podio.jobs_relationships import JOB_MEMBER_FIELDS, upsert_job_member_link
from src.models.MemberModel import Member
from src.models.SubcontractorModel import Subcontractor
from src.models.link_models.JobSubcontractor import JobSubcontractorLink
from src.utils.middleware.logs.logs import logger


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
            for f in item.get("fields", []):
                if f.get("type") == "date":
                    print(
                        f"[DATE FIELD] external_id={f.get('external_id')} values={f.get('values')}")

            mapped = map_podio_item_to_job(item)
            # El batch conoce la app-año de origen: persistirla (REG-015)
            mapped["podio_app_year"] = year

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

            # Descomentar si se quieren hacer pruebas de fallos para la generación de reportes
            """ first_tracking_id = items[0].get("app_item_id_formatted") if items else None

            def mapper_with_forced_diff(item: dict) -> dict:
                mapped = map_podio_item_to_job(item)

                # fuerza diff solo para el primer registro del batch
                if mapped and first_tracking_id and mapped.get("ID_Jobs") == first_tracking_id:
                    mapped["Job_status"] = "__FORCED_DIFF__"

                return mapped """

            # # ✅ VALIDACIÓN POST-MIGRACIÓN (mismo batch)
            # validation = validate_batch_jobs(
            #     items=items,
            #     session=session,
            #     mapper_fn=map_podio_item_to_job,
            #     job_type=job_type,
            #     year=year,
            #     offset=offset,
            #     limit=limit,
            #     report_dir="reports/jobs_validation",
            #     write_report=True
            # )

            # print("🧪 VALIDATION SUMMARY:", validation["summary"])
            # if validation["reports"]:
            #     print("📄 REPORT CSV:", validation["reports"].get("csv"))
            #     print("📄 SUMMARY JSON:",
            #           validation["reports"].get("summary_json"))

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


# ===============================
# ----------- FASE 2 -----------
# ===============================

# SYNC relaciones de Jobs tipo APP
# ----  SYNC Jobs → Relaciones M:1
@retry_db(max_retries=3, delay=1)
def sync_jobs_relation(
    job_type: str,
    year: int,
    target_model,
    source_fk_field: str,
    external_id: str,
    internal_id_field: str,
    limit: int = 30,
    offset: int = 0,
    dry_run: bool = False
):
    """
    Sincroniza una relación dinámica Job → Otro Modelo (APP).

    target_model: Modelo destino (Client, BuildingDept, etc.)
    source_fk_field: Campo FK en Job (ej: "ID_Client")
    external_id: external_id del campo en Podio
    internal_id_field: PK interna del modelo destino
    """

    print(
        f"\n🔗 Sync Jobs → {target_model.__name__} "
        f"| {job_type}-{year} "
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

    updated = 0

    with get_session() as session:
        for item in items:

            podio_item_id = str(item.get("item_id"))
            fields = item.get("fields", [])

            job = session.exec(
                select(Job).where(
                    Job.podio_item_id == podio_item_id
                )
            ).first()

            if not job:
                print(f"⚠️ Job {podio_item_id} no existe en DB")
                continue

            # 🔗 Obtener IDs relacionados
            related_ids = get_related_app_ids(
                fields=fields,
                external_id=external_id,
                session=session,
                model=target_model,
                podio_field="podio_item_id",
                internal_id_field=internal_id_field
            )

            # Protección contra múltiples relaciones
            if len(related_ids) > 1:
                print(
                    f"⚠️ Job {job.ID_Jobs} tiene múltiples "
                    f"{target_model.__name__} en Podio"
                )

            new_value = related_ids[0] if related_ids else None

            current_value = getattr(job, source_fk_field)

            if current_value != new_value:
                updated += 1
                print(
                    f"🟡 Update {job.ID_Jobs} → {source_fk_field}"
                )

                if not dry_run:
                    setattr(job, source_fk_field, new_value)
                    session.add(job)

            else:
                print(
                    f"⚪ {job.ID_Jobs} — sin cambios en "
                    f"{target_model.__name__}"
                )

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "updated": updated,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run,
        "job_type": job_type,
        "year": year,
        "relation": target_model.__name__
    }


# ----  SYNC Jobs → Members tipo APP y CONTACT
@retry_db(max_retries=3, delay=1)
def sync_job_related_members(
    job_type: str,
    year: int,
    limit: int = 30,
    offset: int = 0,
    dry_run: bool = False
):
    """
    Sincroniza relaciones Job ↔ Member (tabla intermedia)
    con rol dinámico dependiendo de la app.
    """

    print(
        f"\n👥 Sync Job ↔ Member | {job_type}-{year} "
        f"| limit={limit} offset={offset} dry_run={dry_run}"
    )

    config = JOB_MEMBER_FIELDS.get((job_type, year))

    if not config:
        logger.warning(
            "No hay configuración de miembros para job_type=%s year=%s", job_type, year)
        return {"processed": 0}

    service = podio_jobs_router.get_service(
        job_type=job_type,
        year=year
    )

    items = service.get_items(limit=limit, offset=offset)

    print(f"📥 Jobs recibidos: {len(items)} | offset={offset}")

    if not items:
        return {"processed": 0}

    created = 0
    updated = 0

    with get_session() as session:

        for item in items:

            fields = item.get("fields", [])
            podio_item_id = str(item.get("item_id"))

            job = session.exec(
                select(Job).where(
                    Job.podio_item_id == podio_item_id
                )
            ).first()

            if not job:
                print(f"⚠️ Job {podio_item_id} no existe")
                continue

            # 🔥 recorrer configuración dinámica
            for external_id, cfg in config.items():

                rol = cfg["rol"]
                field_type = cfg["type"]

                # -----------------------------------
                # CONTACT FIELD
                # -----------------------------------
                if field_type == "contact":

                    profile_ids = get_contact_profile_ids(
                        fields=fields,
                        external_id=external_id
                    )

                    for profile_id in profile_ids:

                        member = session.exec(
                            select(Member).where(
                                Member.podio_profile_id == profile_id
                            )
                        ).first()

                        if not member:
                            continue

                        created_, updated_ = upsert_job_member_link(
                            session,
                            job.ID_Jobs,
                            member.ID_Member,
                            rol,
                            dry_run
                        )

                        created += created_
                        updated += updated_

                # -----------------------------------
                # APP FIELD
                # -----------------------------------
                elif field_type == "app":

                    related_ids = get_related_app_ids(
                        fields=fields,
                        external_id=external_id,
                        session=session,
                        model=Member,
                        podio_field="podio_item_id",
                        internal_id_field="ID_Member"
                    )

                    for member_id in related_ids:

                        created_, updated_ = upsert_job_member_link(
                            session,
                            job.ID_Jobs,
                            member_id,
                            rol,
                            dry_run
                        )

                        created += created_
                        updated += updated_

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "created": created,
        "skipped": updated,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run,
        "job_type": job_type,
        "year": year
    }


# ----  SYNC Jobs → Subcontractors
@retry_db(max_retries=3, delay=1)
def sync_job_related_subcontractor(
    job_type: str,
    year: int,
    limit: int = 30,
    offset: int = 0,
    dry_run: bool = False
):
    """
    Sincroniza relación M:N Job ↔ Subcontractor
    detectando dinámicamente campos technician-* (tipo app).
    """

    print(
        f"\n🔧 Sync Job ↔ Subcontractor | "
        f"{job_type}-{year} | limit={limit} offset={offset}"
    )

    service = podio_jobs_router.get_service(
        job_type=job_type,
        year=year
    )

    items = service.get_items(limit=limit, offset=offset)

    print(f"📥 Jobs recibidos: {len(items)} | offset={offset}")

    if not items:
        return {"processed": 0}

    created = 0

    with get_session() as session:

        for item in items:

            fields = item.get("fields", [])
            podio_item_id = str(item.get("item_id"))

            job = session.exec(
                select(Job).where(
                    Job.podio_item_id == podio_item_id
                )
            ).first()

            if not job:
                print(f"⚠️ Job {podio_item_id} no existe en DB")
                continue

            for f in fields:

                external_id = f.get("external_id")

                # 🔥 Detecta technician-1, technician-2, etc
                if not external_id or not external_id.startswith("technician"):
                    continue

                values = f.get("values", [])
                if not values:
                    continue

                for v in values:

                    podio_related_id = v.get("value", {}).get("item_id")
                    if not podio_related_id:
                        continue

                    subcontractor = session.exec(
                        select(Subcontractor).where(
                            Subcontractor.podio_item_id == str(
                                podio_related_id)
                        )
                    ).first()

                    if not subcontractor:
                        print(
                            f"⚠️ Subcontractor {podio_related_id} "
                            f"no existe en DB"
                        )
                        continue

                    link = session.get(
                        JobSubcontractorLink,
                        (job.ID_Jobs, subcontractor.ID_Subcontractor)
                    )

                    if link:
                        continue

                    created += 1

                    if not dry_run:
                        from sqlalchemy.exc import IntegrityError
                        try:
                            with session.begin_nested():
                                session.add(
                                    JobSubcontractorLink(
                                        job_id=job.ID_Jobs,
                                        subcontr_id=subcontractor.ID_Subcontractor,
                                        position=external_id
                                    )
                                )
                                session.flush()
                        except IntegrityError:
                            # Ya existe o hubo violación de unicidad por concurrencia
                            pass

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "created": created,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run,
        "job_type": job_type,
        "year": year
    }
