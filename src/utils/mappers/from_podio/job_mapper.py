from typing import Optional
import re
from .job_fields_map import FIELD_ALIASES_QID, FIELD_ALIASES_PTL, FIELD_ALIASES_PAR
from ..podio_job_extractor import get_job_field_value


# FASE 1: sin relaciones

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
def map_podio_item_to_job(item: dict, session=None) -> dict:
    """
    Transforma un item de Podio de QID, PTL o PAR para PostgreSQL.
    """

    fields = item.get("fields", [])

    app_item_id_formatted = item.get("app_item_id_formatted")

    job_type = extract_job_type_from_id(app_item_id_formatted)

    if not job_type:
        return {}

    # 🔑 Seleccionar aliases según tipo de job
    if job_type == "QID":
        field_aliases = FIELD_ALIASES_QID
    elif job_type == "PTL":
        field_aliases = FIELD_ALIASES_PTL
    elif job_type == "PAR":
        field_aliases = FIELD_ALIASES_PAR
    else:
        return {}

    job_dict = {
        "podio_item_id": str(item.get("item_id")),
        "ID_Jobs": item.get("app_item_id_formatted"),
        "Job_type": job_type,
    }

    # Mapear dinámicamente usando aliases
    for db_field, field_cfg in field_aliases.items():
        value = get_job_field_value(fields, field_cfg)
        if value is None:
            print(f"[MAP WARN] {job_type} → {db_field} = None")
        job_dict[db_field] = value

    return job_dict
