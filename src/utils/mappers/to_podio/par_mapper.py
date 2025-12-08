from ...convert_value_podio import convert_value_for_podio
from sqlmodel import select
from src.models.ClientModel import Client

PAR_FIELD_MAP = {
    # ----- De Jobs
    # REVISAR CLIENT!!!!
    "Estimated_start_date": "week-assigned",
    "Job_status": "job-status",
    "Gqm_target_sold_pricing": "gqm-target-sold-par",

    # ----- De Order
    # "tech-1-formula",
    # "tech-2-formula",
}


def map_job_to_podio_par(job_obj, session=None):
    payload = {}
    # Campos normales
    for attr, podio_field in PAR_FIELD_MAP.items():
        value = getattr(job_obj, attr, None)
        if value:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Campo relacionado

    return payload
