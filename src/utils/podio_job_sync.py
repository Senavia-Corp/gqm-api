import traceback
from datetime import datetime
from src.models.JobModel import Job
from src.utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid
from src.utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from src.utils.mappers.to_podio.par_mapper import map_job_to_podio_par
from src.podio.services.job_services import podio_jobs_router
from src.utils.mappers.mapper_aux_functions import register_event

def sync_job_to_podio(job_id: str, session) -> None:
    if not job_id:
        return
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
        
        if podio_fields:
            year = job.Date_assigned.year if job.Date_assigned else datetime.now().year
            podio_service = podio_jobs_router.get_service(job_type=job.Job_type, year=year)
            
            # Register the event before update to prevent loopback
            try:
                register_event(job.podio_item_id)
            except Exception:
                pass
            
            podio_service.update_item(int(job.podio_item_id), podio_fields)
            print(f"✅ Automatically synced Job {job_id} to Podio successfully.")
    except Exception as e:
        print(f"❌ Error syncing Job {job_id} to Podio: {e}")
        traceback.print_exc()
