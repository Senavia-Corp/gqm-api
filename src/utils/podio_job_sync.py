import traceback

from src.models.JobModel import Job
from src.models.PodioFailedSyncModel import PodioFailedSync
from src.utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid
from src.utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from src.utils.mappers.to_podio.par_mapper import map_job_to_podio_par
from src.podio.services.job_services import podio_jobs_router
from src.utils.mappers.mapper_aux_functions import register_event
from src.utils.middleware.logs.logs import logger
from src.utils.job_app_year import resolver_anio_app


# La regla canónica vive en src/utils/job_app_year.py. Se conserva el nombre
# porque hay llamadores vivos (Job.py:1116 y :1252).
#
# Antes caía a `Date_assigned.year`: esa rama es la que mandaba los updates a la
# app del año equivocado. El 100 % de los PTL tienen `Date_assigned` NULL, así
# que además dejaba sin año a los 510 PTL de producción y su sync nunca salía.
resolve_job_app_year = resolver_anio_app


def _record_failed_sync(session, job, error) -> None:
    from src.utils.failed_sync import record_failed_sync
    record_failed_sync(
        session,
        item_id=job.podio_item_id,
        hook_type="auto_sync_to_podio",
        payload={"job_id": job.ID_Jobs, "job_type": job.Job_type},
        error=error,
    )


def sync_job_to_podio(job_id: str, session) -> bool:
    """Sincroniza el job a Podio. Devuelve True si sincronizó (o no había
    nada que sincronizar) y False si falló — el /resync usa este valor."""
    if not job_id:
        return False
    job = None
    try:
        job = session.get(Job, job_id)
        if not job or not job.podio_item_id:
            return True  # nada que sincronizar

        podio_fields = None
        if job.Job_type == "QID":
            podio_fields = map_job_to_podio_qid(job, session=session)
        elif job.Job_type == "PTL":
            podio_fields = map_job_to_podio_ptl(job, session=session)
        elif job.Job_type == "PAR":
            podio_fields = map_job_to_podio_par(job, session=session)

        if not podio_fields:
            return True

        year = resolve_job_app_year(job)
        if year is None:
            logger.error(
                "Auto-sync de %s sin año de app resoluble (sin podio_app_year "
                "ni Date_assigned) — no se sincroniza", job_id)
            _record_failed_sync(session, job, "año de app no resoluble")
            return False

        podio_service = podio_jobs_router.get_service(job_type=job.Job_type, year=year)

        # Register the event before update to prevent loopback
        try:
            register_event(job.podio_item_id)
        except Exception:
            pass

        podio_service.update_item(int(job.podio_item_id), podio_fields)
        logger.info("Auto-sync de Job %s a Podio (año %s) OK", job_id, year)
        return True
    except Exception as e:
        logger.error("Error en auto-sync de Job %s a Podio: %s", job_id, e)
        traceback.print_exc()
        if job is not None:
            _record_failed_sync(session, job, e)
        return False
