from ..convert_value_podio import convert_value_for_podio

CLIENT_FIELD_MAP = {
    "Client_Community": "titulo",
    # "Parent_Mgmt_Company": "parent-mgmt-company",
    "Address": "address",
    "Parent_Company": "parent-company",
    "Website": "website-2",
    "Invoice_Collection": "invoicecollection",
    "Compliance_Partner": "compliance-partner",
    "Risk_Value": "risk-value",
    "Prop_Manager": "prop-manager",
    "Email_Address": "email",
    "Phone_Number": "phone",
    "Client_Status": "client-status",
    "Services_interested_in": "services-interested-in",
}


def map_client_to_podio(client_obj):
    payload = {}
    for attr, podio_field in CLIENT_FIELD_MAP.items():
        value = getattr(client_obj, attr, None)
        if value:
            payload[podio_field] = convert_value_for_podio(podio_field, value)
    return payload
