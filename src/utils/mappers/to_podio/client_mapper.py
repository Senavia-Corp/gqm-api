from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from src.models.ParentMgmtCoModel import ParentMgmtCo

CLIENT_FIELD_MAP = {
    "Client_Community": {"podio_field": "title", "type": "text"},
    "Address": {"podio_field": "address", "type": "location"},
    "Website": {"podio_field": "website", "type": "embed"},
    "Invoice_Collection": {"podio_field": "processing", "type": "text"},
    "Compliance_Partner": {"podio_field": "compliance-partner", "type": "category"},
    "Risk_Value": {"podio_field": "engagement-letter-signed", "type": "category"},
    "Maintenance_Sup": {"podio_field": "maintenance-sup", "type": "text"},
    "Email_Address": {"podio_field": "email", "type": "email"},
    "Phone_Number": {"podio_field": "phone", "type": "phone"},
    "Client_Status": {"podio_field": "contact-status", "type": "category"},
    "Services_interested_in": {"podio_field": "services-interested-in", "type": "category"},
    "Collection_Process": {"podio_field": "collection-process", "type": "text"},
    "Payment_Collection": {"podio_field": "payment-coolection", "type": "embed"},
    "Text": {"podio_field": "text", "type": "text"},
}


def map_client_to_podio(client_obj, session=None):
    payload = {}

    # Campos simples
    for attr, config in CLIENT_FIELD_MAP.items():
        value = getattr(client_obj, attr, None)
        # `""` cuenta como ausencia, igual que None. Con `is not None` a secas,
        # un texto vacio en un campo `category`/`tag` llegaba a
        # `convert_value_for_podio` y salia como `[]` — y `[]` en Podio BORRA el
        # campo, en silencio y sin error. Expuestos aqui: Compliance_Partner,
        # Risk_Value, Client_Status y Services_interested_in.
        # Es la misma regla que `1f6d503` fijo para los jobs: que la app no
        # conozca un valor no autoriza a borrarlo en Podio. Vaciar es un acto
        # explicito y va por `limpieza_slots`.
        if value not in (None, ""):
            payload[config["podio_field"]] = convert_value_for_podio(
                value, config["type"])

    # Relación con Parent Mgmt Co (M:1)
    parent_internal_id = client_obj.ID_Community_Tracking

    if parent_internal_id and session:
        parent_mgmt_co = session.exec(
            select(ParentMgmtCo).where(
                ParentMgmtCo.ID_Community_Tracking == parent_internal_id)
        ).first()

        if parent_mgmt_co and parent_mgmt_co.podio_item_id:
            payload["relationship"] = convert_value_for_podio(
                parent_mgmt_co.podio_item_id, "app"
            )

    # Relación con Managers (M:N) se manda desde el link

    return payload
