from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from .job_fields_map import BASE_PTL_FIELDS
from src.models.ClientModel import Client


def map_job_to_podio_ptl(job_obj, session=None):
    payload = {}
    # Campos normales
    for attr, config in BASE_PTL_FIELDS.items():
        value = getattr(job_obj, attr, None)

        # 🔹 DYNAMIC CALCULATION FOR Purchases_list
        if attr == "Purchases_list" and session:
            from src.models.EstimateCostModel import EstimateCost
            from src.models.PurchaseModel import Purchase
            rents = session.exec(
                select(EstimateCost).where(
                    EstimateCost.ID_Jobs == job_obj.ID_Jobs, 
                    EstimateCost.Cost_type == "Rent", 
                    EstimateCost.Status == "Approved"
                )
            ).all()
            purchases = session.exec(
                select(Purchase).where(Purchase.ID_Jobs == job_obj.ID_Jobs)
            ).all()
            p_list = []
            for r in rents:
                p_list.append(float(r.Client_price if r.Client_price is not None else r.Builder_cost or 0))
            for p in purchases:
                p_list.append(float(p.Total_spending or 0))
            value = (p_list + [None]*13)[:13]

        # 🔹 MULTI FIELD
        if config.get("multi"):
            values = value or []
            for i, ext_id in enumerate(config["external_ids"]):
                v = values[i] if i < len(values) else None
                converted = convert_value_for_podio(v, config["type"])
                if converted is not None:
                    payload[ext_id] = converted
                else:
                    payload[ext_id] = []
        
        # 🔹 NORMAL FIELD
        else:
            if value is None:
                continue

            end_value = getattr(job_obj, config["end_attr"], None) if config.get(
                "end_attr") else None
            converted = convert_value_for_podio(
                value, config["type"], end_value=end_value, with_time=config.get("with_time", False))

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
