
from src.utils.mapper_aux_functions import parse_date, clean_html
from sqlmodel import select
from src.models.JobModel import Job


def map_podio_item_to_task(item: dict, session) -> dict:
    """
    Transforma un item de Podio (JSON) al formato de Task para PostgreSQL.
    """
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

    def get_related_job_id():
        # Extrae el ID_Jobs interno a partir del podio_item_id del job relacionado.
        for f in fields:
            if f.get("external_id") == "related-project":
                vals = f.get("values", [])
                if vals:
                    podio_job_item_id = str(vals[0].get(
                        "value", {}).get("app_item_id"))

                    # Buscar en la tabla Jobs por podio_item_id
                    job = session.exec(
                        select(Job).where(
                            Job.podio_item_id == podio_job_item_id)
                    ).first()

                    if job:
                        return job.ID_Jobs
        return None

    task_dict = {
        "podio_item_id": str(item.get("item_id")),
        "Name": get_value("titulo"),
        "Task_description": get_value("description"),
        "Task_status": get_value("status"),
        "Designation_date": parse_date(get_value("deadline")),
        "ID_Jobs": get_related_job_id(session) or "TEMP_JOB",
    }

    return task_dict
