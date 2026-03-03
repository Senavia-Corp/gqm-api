from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from .job_fields_map import BASE_PAR_FIELDS
from src.models.ClientModel import Client


def map_job_to_podio_par(job_obj, session=None):
    payload = {}
    # Campos normales
    for attr, config in BASE_PAR_FIELDS.items():
        value = getattr(job_obj, attr, None)

        if value is None:
            continue

        converted = convert_value_for_podio(
            value,
            config["type"])

        if converted is not None:
            payload[config["external_id"]] = converted

    # Relación con Client (M:1)
    client_internal_id = job_obj.ID_Client

    if client_internal_id and session:
        client = session.exec(
            select(Client).where(Client.ID_Client == client_internal_id)
        ).first()

        if client and client.podio_item_id:
            payload["relationship"] = convert_value_for_podio(
                client.podio_item_id, "app"
            )

    # Relaciones con Members (M:N) se manda desde el link

    # Para debug
    print("🚀 Payload final para Podio:", payload)

    return payload
