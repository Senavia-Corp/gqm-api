from ..convert_value_podio import convert_value_for_podio

PARENT_FIELD_MAP = {
    "Property_mgmt_co": "title",
    "Company_abbrev": "company-abbreviation",
    "Main_office_hq": "main-office-hq",
    "Main_office_email": "main-office-email",
    "Main_office_number": "main-office-number"
}


def map_parent_to_podio(parent_obj, session=None):
    payload = {}

    # Campos simples
    for attr, podio_field in PARENT_FIELD_MAP.items():
        value = getattr(parent_obj, attr, None)
        if value is not None:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Relación con Client se manda desde Client.

    return payload
