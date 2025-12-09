
from ...convert_value_podio import convert_value_for_podio
from sqlmodel import select
from src.models.JobModel import Job


TASKS_FIELD_MAP = {
    "Name": "titulo",
    "Task_description": "description",
    "Task_status": "status",
    "Delivery_date": "deadline",
    # REVISAR RELATED PROJECT (JOB)!!!!
}


def map_task_to_podio(task_obj, session=None):
    payload = {}

    # Campos simples
    for attr, podio_field in TASKS_FIELD_MAP.items():
        value = getattr(task_obj, attr, None)
        if value is not None:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Relación con Job (M:1)
    job_internal_id = task_obj.ID_Jobs

    if job_internal_id and session:
        job = session.exec(
            select(Job).where(Job.ID_Jobs == job_internal_id)
        ).first()

        if job and job.podio_item_id:
            payload["related-project"] = convert_value_for_podio(
                "related-project",
                job.podio_item_id
            )

    return payload
