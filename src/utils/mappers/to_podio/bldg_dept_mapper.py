from ..convert_value_podio import convert_value_for_podio

BLDG_FIELD_MAP = {
    "City_BldgDept": {"podio_field": "title", "type": "text"},
    "Location": {"podio_field": "location", "type": "location"},
    "Office_Email": {"podio_field": "email", "type": "email"},
    "Portal_Log_In": {"podio_field": "potal-log-in", "type": "text"},
    "PW": {"podio_field": "pw", "type": "text"},
    "Phone": {"podio_field": "phone", "type": "phone"},
    "Link": {"podio_field": "link", "type": "embed"},
    "Notes_Inspectors": {"podio_field": "notes-ispectors", "type": "text"},
}


def map_bldg_dept_to_podio(bldg_obj, session=None):
    payload = {}

    # Campos simples
    for attr, config in BLDG_FIELD_MAP.items():
        value = getattr(bldg_obj, attr, None)
        if value is not None:
            payload[config["podio_field"]] = convert_value_for_podio(
                value, config["type"])

    # Relación con QID, PTL y PAR se manda desde Job.

    return payload
