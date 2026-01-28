from ..podio_value_extractor import get_podio_field_value


# FASE 1: sin relaciones
def map_podio_item_to_parent_mgmt_co(item: dict) -> dict:
    """
    Transforma un item de Podio de ParentMgmtCo para PostgreSQL.
    """

    fields = item.get("fields", [])

    return {
        "podio_item_id": str(item.get("item_id")),
        "ID_Community_Tracking": item.get("app_item_id_formatted"),
        "Property_mgmt_co": get_podio_field_value(fields, "title"),
        "Company_abbrev": get_podio_field_value(fields, "company-abbreviation"),
        "Main_office_hq": get_podio_field_value(fields, "main-office-hq"),
        "Main_office_email": get_podio_field_value(fields, "main-office-email"),
        "Main_office_number": get_podio_field_value(fields, "main-office-number"),
    }
