from typing import Optional
import re
from src.utils.mapper_aux_functions import parse_date, clean_html
from .job_fields_map import FIELD_ALIASES
from src.models.ClientModel import Client


# Extraer el Job_type desde el ID del proyecto
def extract_job_type_from_id(project_id: Optional[str]) -> Optional[str]:
    """
    Extrae el tipo de Job (QID, PTL, PAR) desde el ID del proyecto.
    Limpia etiquetas HTML como <p>QID51655</p> antes de procesar.
    """
    if not project_id:
        return None

    # Limpiar etiquetas HTML
    cleaned = re.sub(r"<.*?>", "", str(project_id)).strip().upper()

    if len(cleaned) < 3:
        return None

    prefix = cleaned[:3]
    if prefix in ("QID", "PTL", "PAR"):
        return prefix
    return None


# Mapeo de los datos de Podio a PostgreSQL
def map_podio_item_to_job(item: dict) -> dict:
    """
    Transforma un item de Podio (JSON) al formato de Job para PostgreSQL.
    """
    fields = item.get("fields", [])

    def get_value(field_aliases):
        """
        Acepta una lista de posibles external_id.
        Devuelve el primer valor encontrado.
        """
        if isinstance(field_aliases, str):
            field_aliases = [field_aliases]

        for alias in field_aliases:
            for f in fields:
                if f.get("external_id") == alias:
                    v = f.get("values", f.get("value"))

                    if isinstance(v, list) and v:
                        v = v[0].get("value", v[0]) if isinstance(
                            v[0], dict) else v[0]

                    if isinstance(v, dict) and "text" in v:
                        v = v["text"]

                    return clean_html(v)
        return None

    # Extraer ID del proyecto y job_type
    project_id = get_value(FIELD_ALIASES["ID_Jobs"])
    job_type = extract_job_type_from_id(project_id)

    print(f"🟨 project_id bruto desde Podio: {project_id!r}")
    print(f"🟩 job_type extraído: {job_type}")

    # Crear el diccionario final
    job_dict = {
        "podio_item_id": str(item.get("item_id")),
        "ID_Jobs": get_value(FIELD_ALIASES["ID_Jobs"]),
        "Job_type": job_type,

        "ID_Client": get_value(FIELD_ALIASES["ID_Client"]),
        "Project_location": get_value(FIELD_ALIASES["Project_location"]),
        "Job_status": get_value(FIELD_ALIASES["Job_status"]),
        "Project_name": get_value(FIELD_ALIASES["Project_name"]),
        "Po_wtn_wo": get_value(FIELD_ALIASES["Po_wtn_wo"]),
        "Service_type": get_value(FIELD_ALIASES["Service_type"]),

        "Date_assigned": parse_date(get_value(FIELD_ALIASES["Date_assigned"])),
        "Estimated_start_date": parse_date(get_value(FIELD_ALIASES["Estimated_start_date"])),

        "Gqm_formula_pricing": get_value(FIELD_ALIASES["Gqm_formula_pricing"]),
        "Gqm_adj_formula_pricing": get_value(FIELD_ALIASES["Gqm_adj_formula_pricing"]),
        "Gqm_target_sold_pricing": get_value(FIELD_ALIASES["Gqm_target_sold_pricing"]),
        "Gqm_target_return": get_value(FIELD_ALIASES["Gqm_target_return"]),
        "Gqm_premium_in_money": get_value(FIELD_ALIASES["Gqm_premium_in_money"]),
        "Gqm_final_sold_pricing": get_value(FIELD_ALIASES["Gqm_final_sold_pricing"]),
        "Gqm_final_percentage": get_value(FIELD_ALIASES["Gqm_final_percentage"]),
        "Gqm_total_change_orders": get_value(FIELD_ALIASES["Gqm_total_change_orders"]),
    }

    return job_dict
