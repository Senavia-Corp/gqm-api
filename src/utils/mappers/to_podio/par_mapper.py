from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from .job_fields_map import BASE_PAR_FIELDS
from .limpieza_slots import asignar, normalizar
from src.models.ClientModel import Client


def map_job_to_podio_par(job_obj, session=None, year=None, limpiar_slots=None):
    payload = {}
    limpiar = normalizar(limpiar_slots)
    # Campos normales
    for attr, config in BASE_PAR_FIELDS.items():
        value = getattr(job_obj, attr, None)

        # Vacío = ausencia de dato: ni se convierte. Para los tipos lista,
        # convertir un vacío daría `[]`, que en Podio BORRA el campo. Sólo
        # `limpiar_slots` autoriza ese borrado.
        if value in (None, ""):
            converted = None
        else:
            end_value = getattr(job_obj, config["end_attr"], None) if config.get(
                "end_attr") else None
            if config.get("end_attr") and end_value is None:
                end_value = value
            converted = convert_value_for_podio(
                value, config["type"], end_value=end_value, with_time=config.get("with_time", False))

        asignar(payload, config["external_id"], converted, limpiar)

    # Relación con Client (M:1). Que la app no sepa el cliente no autoriza a
    # desvincularlo en Podio: sólo se vacía si se pide por `limpiar_slots`.
    client_internal_id = job_obj.ID_Client
    client_valor = None

    if client_internal_id and session:
        client = session.exec(
            select(Client).where(Client.ID_Client == client_internal_id)
        ).first()

        if client and client.podio_item_id:
            client_valor = convert_value_for_podio(client.podio_item_id, "app")

    asignar(payload, "relationship", client_valor, limpiar)

    # Relaciones con Members y Subcontractors (M:N) se mandan desde los links

    # Para debug
    print("🚀 Payload final para Podio:", payload)

    return payload
