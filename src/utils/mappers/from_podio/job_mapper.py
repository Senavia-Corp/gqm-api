from typing import Optional
import re
from sqlmodel import select
from src.utils.mappers.mapper_aux_functions import parse_date, clean_html
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
def map_podio_item_to_job(item: dict, session=None) -> dict:
    fields = item.get("fields", [])

    app_item_id_formatted = item.get("app_item_id_formatted")

    def get_value(field_aliases):
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

                    if f.get("type") == "calculation" and v is not None:
                        try:
                            v = float(v)
                        except (TypeError, ValueError):
                            v = None

                    return clean_html(v)
        return None

    def get_related_client_id(session):
        aliases = FIELD_ALIASES.get("ID_Client", ["client"])
        for alias in aliases:
            for f in fields:
                if f.get("external_id") == alias:
                    vals = f.get("values", [])
                    if vals:
                        podio_client_id = str(vals[0].get("value", {}).get(
                            "item_id"))
                        if podio_client_id and session:
                            client = session.exec(
                                select(Client).where(
                                    Client.podio_item_id == podio_client_id)
                            ).first()
                            if client:
                                return client.ID_Client
                            else:
                                print(
                                    f"⚠️ Podio client item_id {podio_client_id} no existe en DB")
                                return None
        return None

    job_type = extract_job_type_from_id(app_item_id_formatted)

    # AGREGAR LOS CAMPOS DE CALCULATION !!!!!!!!!!
    job_dict = {
        "podio_item_id": str(item.get("item_id")),
        "ID_Jobs": app_item_id_formatted,
        "Job_type": job_type,
        "ID_Client": get_related_client_id(session),
        "Project_location": get_value(FIELD_ALIASES["Project_location"]),
        "Job_status": get_value(FIELD_ALIASES["Job_status"]),
        "Project_name": get_value(FIELD_ALIASES["Project_name"]),
        "Po_wtn_wo": get_value(FIELD_ALIASES["Po_wtn_wo"]),
        "Service_type": get_value(FIELD_ALIASES["Service_type"]),
        "Date_assigned": parse_date(get_value(FIELD_ALIASES["Date_assigned"])),
        "Estimated_start_date": parse_date(get_value(FIELD_ALIASES["Estimated_start_date"])),
        "Gqm_target_sold_pricing": get_value(FIELD_ALIASES["Gqm_target_sold_pricing"]),
    }

    return job_dict
