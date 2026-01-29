from ..podio_value_extractor import get_podio_field_value


# FASE 1: sin relaciones
def map_podio_item_to_client(item: dict, session=None) -> dict:
    """
    Transforma un item de Podio de Client para PostgreSQL.
    """
    fields = item.get("fields", [])

    return {
        "podio_item_id": str(item.get("item_id")),

        "Client_Community": get_podio_field_value(fields, "title"),
        "Address": get_podio_field_value(fields, "address"),
        "Website": get_podio_field_value(fields, "website"),
        "Invoice_Collection": get_podio_field_value(fields, "processing"),
        "Compliance_Partner": get_podio_field_value(fields, "compliance-partner"),
        "Risk_Value": get_podio_field_value(fields, "engagement-letter-signed"),
        "Maintenance_Sup": get_podio_field_value(fields, "maintenance-sup"),
        "Email_Address": get_podio_field_value(fields, "email"),
        "Phone_Number": get_podio_field_value(fields, "phone"),
        "Client_Status": get_podio_field_value(fields, "contact-status"),
        "Services_interested_in": get_podio_field_value(fields, "services-interested-in"),
        "Collection_Process": get_podio_field_value(fields, "collection-process"),
        "Payment_Collection": get_podio_field_value(fields, "payment-coolection"),
        "Text": get_podio_field_value(fields, "text"),
    }
