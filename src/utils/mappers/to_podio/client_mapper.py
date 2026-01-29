from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from src.models.ParentMgmtCoModel import ParentMgmtCo

CLIENT_FIELD_MAP = {
    "Client_Community": "title",
    "Address": "address",
    "Website": "website",
    "Invoice_Collection": "processing",
    "Compliance_Partner": "compliance-partner",
    "Risk_Value": "engagement-letter-signed",
    "Maintenance_Sup": "maintenance-sup",
    "Email_Address": "email",
    "Phone_Number": "phone",
    "Client_Status": "contact-status",
    "Services_interested_in": "services-interested-in",
    "Collection_Process": "collection-process",
    "Payment_Collection": "payment-coolection",
    "Text": "text"

}


def map_client_to_podio(client_obj, session=None):
    payload = {}

    # Campos simples
    for attr, podio_field in CLIENT_FIELD_MAP.items():
        value = getattr(client_obj, attr, None)
        if value is not None:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Relación con Parent Mgmt Co (M:1)
    parent_internal_id = client_obj.ID_Community_Tracking

    if parent_internal_id and session:
        parent_mgmt_co = session.exec(
            select(ParentMgmtCo).where(
                ParentMgmtCo.ID_Community_Tracking == parent_internal_id)
        ).first()

        if parent_mgmt_co and parent_mgmt_co.podio_item_id:
            payload["relationship"] = convert_value_for_podio(
                "relationship",
                parent_mgmt_co.podio_item_id
            )

    return payload
