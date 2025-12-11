from ...convert_value_podio import convert_value_for_podio
from sqlmodel import select
from src.models.ClientModel import Client


QID_FIELD_MAP = {
    # ----- De Jobs
    "Project_location": "project-location-2",
    "Job_status": "job-status-2",
    "Project_name": "project-name-2",
    "Po_wtn_wo": "powtnwo",
    "Service_type": "service-type-3",
    "Date_assigned": "date-assigned-2",
    "Gqm_target_sold_pricing": "gqm-target-sold-pricing-2",

    # ----- De Order
    # "tech-1-formula-2",
    # "tech-2-formula",

    # ----- De Estimate Cost
    # "estimated-rent-total-2",
    # "estimated-material-total-2",
    # "estimated-city-permits-total",
    # "bldg-dept-fees-1",
    # "bldg-dept-fees-2",
    # "bldg-dept-fees-3",
    # "purchase-1",
    # "purchase-2",
    # "purchase-3"
}


def map_job_to_podio_qid(job_obj, session=None):
    payload = {}
    # Campos normales
    for attr, podio_field in QID_FIELD_MAP.items():
        value = getattr(job_obj, attr, None)
        if value:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Relación con Client (M:1)
    client_internal_id = job_obj.ID_Client

    if client_internal_id and session:
        client = session.exec(
            select(Client).where(Client.ID_Client == client_internal_id)
        ).first()

        if client and client.podio_item_id:
            payload["client-2"] = convert_value_for_podio(
                "client-2",
                client.podio_item_id
            )

    # Para debug
    print("🚀 Payload final para Podio:", payload)

    return payload
