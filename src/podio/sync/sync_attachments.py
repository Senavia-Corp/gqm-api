import requests
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.podio.podio_auth import get_podio_headers
from src.models.AttachmentsModel import Attachments
from src.models.JobModel import Job
from src.utils.podio_webhook_core import process_item_attachments


# ------------- SYNC DE ATTACHMENTS POR ENTIDAD (no Job) ------------ #
def sync_entity_attachments_by_id(app_type: str, entity_id: str,
                                  podio_item_id: str, dry_run: bool = False):
    """Recupera los adjuntos de una entidad que NO es un Job.

    `sync_job_attachments_by_id` lanza `ValueError` si el ID no empieza por
    QID/PTL/PAR, asi que los adjuntos de subcontratistas, building departments,
    clientes y communities no tenian NINGUN recuperador: si su entrega fallaba,
    el fichero se quedaba perdido y el boton del panel no servia.

    Exposicion real medida en produccion el 25-ago-2026: 18 adjuntos con
    ID_Subcontractor, 3 con ID_BldgDept y 3 en carpeta CLI.
    """
    from src.utils.podio_webhook_core import ATTACHMENT_MODEL_MAP

    if app_type not in ATTACHMENT_MODEL_MAP:
        raise ValueError(
            f"app_type {app_type} no esta en ATTACHMENT_MODEL_MAP; no se sabe "
            f"a que columna colgar sus adjuntos")

    print(f"\n📎 Sync Attachments por entidad | {app_type} {entity_id}")

    with get_session() as session:
        headers = get_podio_headers(app_type)
        response = requests.get(
            f"https://api.podio.com/item/{podio_item_id}", headers=headers)
        response.raise_for_status()
        files = response.json().get("files", [])
        print(f"📁 Archivos encontrados en Podio: {len(files)}")

        if not files:
            return {"processed": 0, "created": 0, "skipped": 0, "fallidos": 0,
                    "file_ids_fallidos": [], "entity_id": entity_id,
                    "message": "No hay archivos adjuntos en esta entidad."}

        if dry_run:
            return {"processed": len(files), "created": 0, "skipped": 0,
                    "fallidos": 0, "file_ids_fallidos": [],
                    "entity_id": entity_id, "dry_run": True}

        conteos = process_item_attachments(
            session=session, files=files, app_type=app_type,
            entity_id=entity_id)
        session.commit()

        return {
            "processed":         len(files),
            "created":           conteos["creados"],
            "skipped":           conteos["omitidos"],
            "fallidos":          conteos["fallidos"],
            "file_ids_fallidos": conteos["file_ids_fallidos"],
            "entity_id":         entity_id,
            "dry_run":           False,
        }


# ------------- SYNC DE ATTACHMENTS POR JOB ------------ #
def sync_job_attachments_by_id(
    id_jobs: str,
    year: int,
    dry_run: bool = False
):
    """
    Trae los archivos adjuntos de un Job específico desde Podio
    y los sincroniza con Cloudinary y DB.

    Deriva el app_type del prefijo del ID_Jobs (ej: QID51894 → QID)
    y busca el podio_item_id internamente.
    """
    print(f"\n📎 Sync Attachments por Job | {id_jobs} | year={year}")

    # ── 1. Derivar app_type del ID_Jobs ──────────────────────────
    job_type = None
    for prefix in ["QID", "PTL", "PAR"]:
        if id_jobs.upper().startswith(prefix):
            job_type = prefix
            break

    if not job_type:
        raise ValueError(f"No se pudo derivar app_type del ID_Jobs: {id_jobs}")

    # ── 2. Buscar el Job en DB ────────────────────────────────────
    with get_session() as session:
        job = session.exec(
            select(Job).where(Job.ID_Jobs == id_jobs)
        ).first()

        if not job:
            raise ValueError(f"Job {id_jobs} no encontrado en DB.")

        if not job.podio_item_id:
            raise ValueError(
                f"Job {id_jobs} no tiene podio_item_id registrado.")

        # ── 3. Llamar a Podio para obtener el item completo ───────
        print(f"🔍 Consultando Podio | podio_item_id={job.podio_item_id}")

        headers = get_podio_headers(job_type, year=year)
        response = requests.get(
            f"https://api.podio.com/item/{job.podio_item_id}",
            headers=headers
        )
        response.raise_for_status()
        podio_item = response.json()

        files = podio_item.get("files", [])
        print(f"📁 Archivos encontrados en Podio: {len(files)}")

        if not files:
            return {
                "processed": 0,
                "created":   0,
                "skipped":   0,
                "fallidos":  0,
                "file_ids_fallidos": [],
                "id_jobs":   id_jobs,
                "message":   "No hay archivos adjuntos en este Job."
            }

        # ── 4. Contar skips ───────────────────────────────────────
        existing_count = sum(
            1 for f in files
            if session.exec(
                select(Attachments).where(
                    Attachments.podio_file_id == str(f.get("file_id"))
                )
            ).first()
        )
        skipped = existing_count

        if dry_run:
            return {
                "processed": len(files),
                "created":   len(files) - existing_count,
                "skipped":   skipped,
                "fallidos":  0,
                "file_ids_fallidos": [],
                "id_jobs":   id_jobs,
                "dry_run":   True
            }

        # ── 5. Procesar archivos ──────────────────────────────────
        # `created` se deducia restando longitudes (after - before). Eso no
        # distingue "no habia nada que crear" de "fallaron los tres": las dos
        # dan 0, y el llamador respondia ✅ en ambos casos. Ahora los conteos
        # los lleva quien procesa cada fichero y aqui solo se propagan.
        conteos = process_item_attachments(
            session=session,
            files=files,
            app_type=job_type,
            year=year,
            id_jobs=id_jobs
        )

        session.commit()

        print(f"✅ Sync completado | created={conteos['creados']} "
              f"skipped={conteos['omitidos']} fallidos={conteos['fallidos']}")

        return {
            "processed":         len(files),
            "created":           conteos["creados"],
            "skipped":           conteos["omitidos"],
            "fallidos":          conteos["fallidos"],
            "file_ids_fallidos": conteos["file_ids_fallidos"],
            "id_jobs":           id_jobs,
            "dry_run":           False
        }
