import traceback

from src.models.JobModel import Job
from src.models.PodioFailedSyncModel import PodioFailedSync
from src.utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid
from src.utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from src.utils.mappers.to_podio.par_mapper import map_job_to_podio_par
from src.podio.services.job_services import podio_jobs_router
from src.utils.mappers.mapper_aux_functions import register_event
from src.utils.middleware.logs.logs import logger


def resolve_job_app_year(job) -> int | None:
    """Año de la app Podio del job: el persistido, o Date_assigned como
    fallback histórico. Nunca now() — adivinar el año manda el update a la
    app equivocada (REG-015)."""
    if job.podio_app_year:
        return job.podio_app_year
    if job.Date_assigned:
        return job.Date_assigned.year
    return None


def _record_failed_sync(session, job, error: str) -> None:
    try:
        session.add(PodioFailedSync(
            item_id=str(job.podio_item_id) if job.podio_item_id else None,
            hook_type="auto_sync_to_podio",
            payload={"job_id": job.ID_Jobs, "job_type": job.Job_type},
            error_message=error[:2000],
        ))
        session.commit()
    except Exception:
        logger.exception("No se pudo registrar PodioFailedSync para %s", job.ID_Jobs)


def sync_job_to_podio(job_id: str, session) -> None:
    if not job_id:
        return
    job = None
    try:
        job = session.get(Job, job_id)
        if not job or not job.podio_item_id:
            return

        podio_fields = None
        if job.Job_type == "QID":
            podio_fields = map_job_to_podio_qid(job, session=session)
        elif job.Job_type == "PTL":
            podio_fields = map_job_to_podio_ptl(job, session=session)
        elif job.Job_type == "PAR":
            podio_fields = map_job_to_podio_par(job, session=session)

        if not podio_fields:
            return

        year = resolve_job_app_year(job)
        if year is None:
            logger.error(
                "Auto-sync de %s sin año de app resoluble (sin podio_app_year "
                "ni Date_assigned) — no se sincroniza", job_id)
            _record_failed_sync(session, job, "año de app no resoluble")
            return

        podio_service = podio_jobs_router.get_service(job_type=job.Job_type, year=year)

        # Register the event before update to prevent loopback
        try:
            register_event(job.podio_item_id)
        except Exception:
            pass

        podio_service.update_item(int(job.podio_item_id), podio_fields)
        logger.info("Auto-sync de Job %s a Podio (año %s) OK", job_id, year)
    except Exception as e:
        logger.error("Error en auto-sync de Job %s a Podio: %s", job_id, e)
        traceback.print_exc()
        if job is not None:
            _record_failed_sync(session, job, str(e))
