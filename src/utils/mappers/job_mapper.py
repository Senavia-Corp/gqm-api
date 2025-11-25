from typing import Optional
import re
from src.utils.mapper_aux_functions import parse_date, clean_html


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

    def get_value(field_name: str) -> Optional[str]:
        """
        Extrae el valor de un campo de Podio usando su external_id.
        Siempre devuelve un string limpio si es posible.
        """
        for f in fields:
            if f.get("external_id") == field_name:
                v = f.get("values", f.get("value"))

                # Si es lista, tomar el primer valor
                if isinstance(v, list) and v:
                    v = v[0].get("value", v[0]) if isinstance(
                        v[0], dict) else v[0]

                # Si es un dict con 'text'
                if isinstance(v, dict) and "text" in v:
                    v = v["text"]

                # Limpiar HTML
                if v is not None:
                    return clean_html(v)
        return None

    # Extraer ID del proyecto y job_type
    project_id = get_value("id-projects-workorder")
    job_type = extract_job_type_from_id(project_id)

    print(f"🟨 project_id bruto desde Podio: {project_id!r}")
    print(f"🟩 job_type extraído: {job_type}")

    # Crear el diccionario final
    job_dict = {
        "podio_item_id": str(item.get("item_id")),  # Podio item_id
        "ID_Jobs": str(project_id),                 # tu ID interno como string
        "Job_type": job_type,
        "Project_location": get_value("project-location"),
        "Job_status": get_value("job-status"),
        "Project_name": get_value("project-name-2"),
        "Po_wtn_wo": get_value("powtnwo"),
        "Service_type": get_value("service-type"),
        "Date_assigned": parse_date(get_value("date-assigned")),
        "Estimated_start_date": parse_date(get_value("estimated-start-date")),
        "Estimated_project_duration": get_value("estimated-project-duration"),
        "Gqm_formula_pricing": get_value("gqm-formula-pricing"),
        "Gqm_adj_formula_pricing": get_value("gqm-adj-formula-pricing"),
        "Gqm_target_sold_pricing": get_value("gqm-target-sold-pricing"),
        "Gqm_target_return": get_value("gqm-target-return"),
        "Gqm_premium_in_money": get_value("2023-gqm-final"),
        "Gqm_final_sold_pricing": get_value("gqm-final-sold-pricing"),
        "Gqm_final_percentage": get_value("gqm-final-percentage"),
        "Gqm_total_change_orders": get_value("gqm-total-change-orders"),
    }

    return job_dict
