from ..convert_value_podio import convert_value_for_podio

PARENT_FIELD_MAP = {
    "Property_mgmt_co": {"podio_field": "title", "type": "text"},
    "Company_abbrev": {"podio_field": "company-abbreviation", "type": "text"},
    "Main_office_hq": {"podio_field": "main-office-hq", "type": "location"},
    "Main_office_email": {"podio_field": "main-office-email", "type": "email"},
    "Main_office_number": {"podio_field": "main-office-number", "type": "phone"},
}


def map_parent_to_podio(parent_obj, session=None):
    payload = {}

    # Campos simples
    for attr, config in PARENT_FIELD_MAP.items():
        value = getattr(parent_obj, attr, None)
        if value is not None:
            payload[config["podio_field"]] = convert_value_for_podio(
                value, config["type"])

    # Relación con Client se manda desde Client.

    return payload
