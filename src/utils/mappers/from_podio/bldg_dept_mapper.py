from ..podio_value_extractor import get_podio_field_value


# FASE 1: sin relaciones (NO REQUIERE FASE 2)
def map_podio_item_to_bldg_dept(item: dict, session=None) -> dict:
    """
    Transforma un item de Podio de Building Department para PostgreSQL.
    """

    fields = item.get("fields", [])

    return {
        "podio_item_id": str(item.get("item_id")),
        "ID_BldgDept": item.get("app_item_id_formatted"),
        "City_BldgDept": get_podio_field_value(fields, "title"),
        "Location": get_podio_field_value(fields, "location"),
        "Office_Email": get_podio_field_value(fields, "email"),
        "Portal_Log_In": get_podio_field_value(fields, "potal-log-in"),
        "PW": get_podio_field_value(fields, "pw"),
        "Phone": get_podio_field_value(fields, "phone"),
        "Link": get_podio_field_value(fields, "link"),
        "Notes_Inspectors": get_podio_field_value(fields, "notes-ispectors"),
    }
