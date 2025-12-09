from typing import Optional
from src.utils.mapper_aux_functions import parse_date, clean_html

# Mapeo de los datos de Podio a PostgreSQL para Client


def map_podio_item_to_client(item: dict) -> dict:
    """
    Transforma un item de Podio (JSON) al formato de Client para PostgreSQL.
    """
    fields = item.get("fields", [])

    def get_value(field_name: str):
        for f in fields:
            if f.get("external_id") == field_name or f.get("label") == field_name:
                raw = f.get("values") or f.get("value")

                # Si es lista, tomar primer valor
                if isinstance(raw, list) and raw:
                    raw = raw[0]

                # ---------------------------
                # 1️⃣ Campos tipo EMBED
                # ---------------------------
                if isinstance(raw, dict) and "embed" in raw:
                    embed = raw.get("embed", {})
                    return embed.get("url") or embed.get("perma_link") or embed.get("original_url")

                # ---------------------------
                # 2️⃣ Campos con {"value": "..."}
                # ---------------------------
                if isinstance(raw, dict) and "value" in raw and not isinstance(raw["value"], dict):
                    return clean_html(raw["value"])

                # ---------------------------
                # 3️⃣ Campos option: {"name": "..."}
                # ---------------------------
                if isinstance(raw, dict) and "name" in raw:
                    return clean_html(raw["name"])

                # ---------------------------
                # 4️⃣ Campos texto: {"text": "..."}
                # ---------------------------
                if isinstance(raw, dict) and "text" in raw:
                    return clean_html(raw["text"])

                # ---------------------------
                # 5️⃣ Ya es un valor limpio (str/int)
                # ---------------------------
                if not isinstance(raw, dict):
                    return clean_html(raw)

                # ---------------------------
                # 6️⃣ Fallback final
                # ---------------------------
                return None

        return None

    client_dict = {
        "podio_item_id": str(item.get("item_id")),
        "Client_Community": get_value("titulo"),
        # "Parent_Mgmt_Company": get_value("parent-mgmt-company"),
        "Parent_Company": get_value("parent-company"),
        "Address": get_value("address"),
        "Website": get_value("website-2"),
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
