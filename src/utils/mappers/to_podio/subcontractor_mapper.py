from ..convert_value_podio import convert_value_for_podio

SUBC_FIELD_MAP = {
    "Organization": "organization",
    "Name": "name",
    "Email_Address": "email-address",
    "Phone_Number": "phone-number",
    "Organization_Website": "website",
    "Address": "address",
    "Status": "status",
    "Gqm_compliance": "gqm-compliace-req",
    "Gqm_best_service_training": "gqm-best-service-training",
    "Specialty": "job-title",
    "Coverage_Area": "coverage-area",
    "Notes": "notes"
}


def map_subc_to_podio(subc_obj, session=None):
    payload = {}

    # Campos simples
    for attr, podio_field in SUBC_FIELD_MAP.items():
        value = getattr(subc_obj, attr, None)
        if value is not None:
            payload[podio_field] = convert_value_for_podio(podio_field, value)

    # Relación en QID, PTL y PAR se manda desde Jobs

    return payload
