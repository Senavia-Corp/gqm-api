from ...convert_value_podio import convert_value_for_podio
from sqlmodel import select
from src.models.ClientModel import Client

PTL_FIELD_MAP = {
    # ----- De Jobs
    # REVISAR CLIENT!!!!
    "Project_location": "location",
    "Job_status": "categoria",
    "Estimated_start_date": "estimated-start-date",
    "Gqm_target_sold_pricing": "ptl-cost",
    # "ID_Member": "mgmt-member",

    # ----- De Order
    # "tech-1-ptl-original-pricing",
    # "tech-1-ptl-original-pricing-2",

    # ----- De Estimate Cost
}


def map_job_to_podio_ptl(job_obj, session=None):
    payload = {}
    # Campos normales
    for attr, podio_field in PTL_FIELD_MAP.items():
        value = getattr(job_obj, attr, None)
        if value:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Campo relacionado

    return payload
