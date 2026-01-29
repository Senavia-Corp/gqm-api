from ..podio_value_extractor import get_podio_field_value


# FASE 1: sin relaciones
def map_podio_item_to_subc(item: dict, session=None) -> dict:
    """
    Transforma un item de Podio (JSON) al formato de Subcontractor para PostgreSQL.
    """
    fields = item.get("fields", [])

    subc_dict = {
        "podio_item_id": str(item.get("item_id")),
        "Organization": get_podio_field_value(fields, "organization"),
        "Name": get_podio_field_value(fields, "name"),
        "Email_Address": get_podio_field_value(fields, "email-address"),
        "Phone_Number": get_podio_field_value(fields, "phone-number"),
        "Organization_Website": get_podio_field_value(fields, "website"),
        "Address": get_podio_field_value(fields, "address"),
        "Status": get_podio_field_value(fields, "status"),
        "Gqm_compliance": get_podio_field_value(fields, "gqm-compliace-req"),
        "Gqm_best_service_training": get_podio_field_value(fields, "gqm-best-service-training"),
        "Specialty": get_podio_field_value(fields, "job-title"),
        "Coverage_Area": get_podio_field_value(fields, "coverage-area"),
        "Notes": get_podio_field_value(fields, "notes")
    }

    return subc_dict
