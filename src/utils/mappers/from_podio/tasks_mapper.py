
from src.utils.mapper_aux_functions import parse_date, clean_html
from sqlmodel import select
from src.models.JobModel import Job
from .job_fields_map import FIELD_ALIASES


def map_podio_item_to_task(item: dict, session) -> dict:
    fields = item.get("fields", [])

    def get_value(field_name: str):
        for f in fields:
            if f.get("external_id") == field_name or f.get("label") == field_name:
                v = f.get("values", f.get("value"))
                if isinstance(v, list) and v:
                    v = v[0].get("value", v[0]) if isinstance(
                        v[0], dict) else v[0]
                if isinstance(v, dict) and "text" in v:
                    v = v["text"]
                return clean_html(v)
        return None

    def get_related_job_id(session):
        aliases = ["related-project"]  # o el external_id que uses en Podio
        for alias in aliases:
            for f in fields:
                if f.get("external_id") == alias:
                    vals = f.get("values", [])
                    if vals:
                        podio_job_item_id = str(vals[0].get(
                            "value", {}).get("item_id"))  # usar item_id
                        if podio_job_item_id and session:
                            job = session.exec(
                                select(Job).where(
                                    Job.podio_item_id == podio_job_item_id)
                            ).first()
                            if job:
                                return job.ID_Jobs
                            else:
                                print(
                                    f"⚠️ Task tiene Job Podio item_id {podio_job_item_id} que no existe en DB")
                                return None
        return None

    task_dict = {
        "podio_item_id": str(item.get("item_id")),
        "Name": get_value("titulo"),
        "Task_description": get_value("description"),
        "Task_status": get_value("status"),
        "Delivery_date": parse_date(get_value("deadline")),
        "ID_Jobs": get_related_job_id(session),
    }

    return task_dict
