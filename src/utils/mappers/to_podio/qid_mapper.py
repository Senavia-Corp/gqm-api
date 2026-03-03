from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from .job_fields_map import BASE_QID_FIELDS
from src.models.ClientModel import Client
from src.models.BldgDeptModel import BuildingDept


def map_job_to_podio_qid(job_obj, session=None):
    payload = {}
    # Campos normales
    for attr, config in BASE_QID_FIELDS.items():
        value = getattr(job_obj, attr, None)

        # 🔹 MULTI FIELD (Bldg_dept_fees)
        if config.get("multi"):
            values = value or []

            for i, ext_id in enumerate(config["external_ids"]):
                v = values[i] if i < len(values) else None

                converted = convert_value_for_podio(
                    v,
                    config["type"])

                if converted is not None:
                    payload[ext_id] = converted

        # 🔹 NORMAL FIELD
        else:
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

    # Relación con Building Department (M:1)
    bldg_internal_id = job_obj.ID_BldgDept

    if bldg_internal_id and session:
        bldg_dept = session.exec(
            select(BuildingDept).where(
                BuildingDept.ID_BldgDept == bldg_internal_id)
        ).first()

        if bldg_dept and bldg_dept.podio_item_id:
            payload["bldg-dept"] = convert_value_for_podio(
                bldg_dept.podio_item_id, "app"
            )

    # Relaciones con Members (M:N) se manda desde el link

    # Para debug
    print("🚀 Payload final para Podio:", payload)

    return payload
