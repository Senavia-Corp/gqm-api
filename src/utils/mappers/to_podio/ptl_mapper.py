from ...convert_value_podio import convert_value_for_podio
from sqlmodel import select
from src.models.ClientModel import Client

PTL_FIELD_MAP = {
    # ----- De Jobs
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

    # # Relación con Client (M:1)
    client_internal_id = job_obj.ID_Client

    if client_internal_id and session:
        client = session.exec(
            select(Client).where(Client.ID_Client == client_internal_id)
        ).first()

        if client and client.podio_item_id:
            payload["client"] = convert_value_for_podio(
                "client",
                client.podio_item_id
            )

    # Para debug
    print("🚀 Payload final para Podio:", payload)

    return payload
