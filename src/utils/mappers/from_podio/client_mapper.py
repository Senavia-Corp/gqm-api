from typing import Optional
from src.utils.mapper_aux_functions import parse_date, clean_html

# Mapeo de los datos de Podio a PostgreSQL para Client


def map_podio_item_to_client(item: dict) -> dict:
    """
    Transforma un item de Podio (JSON) al formato de Client para PostgreSQL.
    """
    fields = item.get("fields", [])

    def get_value(field_name: str):
        """
        Busca un field por external_id o label y devuelve su valor limpio.
        """
        for f in fields:
            # Se busca por external_id primero, si no existe se usa label
            if f.get("external_id") == field_name or f.get("label") == field_name:
                v = f.get("values", f.get("value"))

                if isinstance(v, list) and v:
                    v = v[0].get("value", v[0]) if isinstance(
                        v[0], dict) else v[0]

                if isinstance(v, dict) and "text" in v:
                    v = v["text"]

                return clean_html(v)
        return None

    client_dict = {
        "podio_item_id": str(item.get("item_id")),
        "Client_Community": get_value("titulo"),
        "Parent_Mgmt_Company": get_value("parent-mgmt-company"),
        "Parent_Company": get_value("parent-company"),
        "Address": get_value("address"),
        "Website": get_value("website"),
        "Invoice_Collection": get_value("invoicecollection"),
        "Compliance_Partner": get_value("compliance-partner"),
        "Risk_Value": get_value("risk-value"),
        "Prop_Manager": get_value("prop-manager"),
        "Email_Address": get_value("email"),
        "Phone_Number": get_value("phone"),
        "Client_Status": get_value("client-status"),
        "Services_interested_in": get_value("services-interested-in"),
    }

    return client_dict
