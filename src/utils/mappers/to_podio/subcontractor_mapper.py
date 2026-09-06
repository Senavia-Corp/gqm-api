from ..convert_value_podio import convert_value_for_podio

SUBC_FIELD_MAP = {
    "Organization": {"podio_field": "organization", "type": "tag"},
    "Name": {"podio_field": "name", "type": "text"},
    "Email_Address": {"podio_field": "email-address", "type": "email"},
    "Phone_Number": {"podio_field": "phone-number", "type": "phone"},
    "Organization_Website": {"podio_field": "website", "type": "embed"},
    "Address": {"podio_field": "address", "type": "location"},
    "Status": {"podio_field": "status", "type": "category"},
    "Gqm_compliance": {"podio_field": "gqm-compliace-req", "type": "category"},
    "Gqm_best_service_training": {"podio_field": "gqm-best-service-training", "type": "category"},
    "Specialty": {"podio_field": "job-title", "type": "text"},
    "Coverage_Area": {"podio_field": "coverage-area", "type": "category"},
    "Notes": {"podio_field": "notes", "type": "text"}
}


def map_subc_to_podio(subc_obj, session=None):
    payload = {}

    # Campos simples
    for attr, config in SUBC_FIELD_MAP.items():
        value = getattr(subc_obj, attr, None)
        # `""` cuenta como ausencia, igual que None: en un campo `category`/`tag`
        # salia como `[]`, y `[]` en Podio BORRA el campo sin error. Expuestos
        # aqui: Organization (tag), Status, Gqm_compliance,
        # Gqm_best_service_training y Coverage_Area. Misma regla que `1f6d503`.
        if value not in (None, ""):
            payload[config["podio_field"]] = convert_value_for_podio(
                value, config["type"])

    # Relación con Skills para Division Trade se manda desde el link

    # Relación en QID, PTL y PAR se manda desde Jobs.

    return payload
