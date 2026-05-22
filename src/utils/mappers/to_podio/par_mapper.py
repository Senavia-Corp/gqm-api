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

        end_value = getattr(job_obj, config["end_attr"], None) if config.get(
            "end_attr") else None
        converted = convert_value_for_podio(
            value, config["type"], end_value=end_value)

        if converted is not None:
            payload[config["external_id"]] = converted

    # Relación con Client (M:1)
    # Si ID_Client es null → mandamos [] para LIMPIAR el campo en Podio
    client_internal_id = job_obj.ID_Client

    if client_internal_id and session:
        client = session.exec(
            select(Client).where(Client.ID_Client == client_internal_id)
        ).first()

        if client and client.podio_item_id:
            payload["relationship"] = convert_value_for_podio(
                client.podio_item_id, "app"
            )
        else:
            payload["relationship"] = []
    else:
        payload["relationship"] = []

    # Relaciones con Members y Subcontractors (M:N) se mandan desde los links

    # Para debug
    print("🚀 Payload final para Podio:", payload)

    return payload
