from ...convert_value_podio import convert_value_for_podio

TASKS_FIELD_MAP = {
    "Name": "titulo",
    "Task_description": "description",
    "Task_status": "status",
    "Designation_date": "deadline",
}


def map_task_to_podio(task_obj):
    payload = {}

    # Campos normales
    for attr, podio_field in TASKS_FIELD_MAP.items():
        value = getattr(task_obj, attr, None)
        if value:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Campo relacionado a Job
    job_id = getattr(task_obj, "ID_Jobs", None)
    if job_id:
        # Podio espera una lista de valores con diccionarios que tengan 'app_item_id'
        payload["related-project"] = [{"value": {"app_item_id": int(job_id)}}]

    return payload
