from typing import Optional
from datetime import datetime
import re


def parse_date(value: Optional[str]) -> Optional[datetime.date]:

    # Convierte string de Podio a datetime.date.
    if not value:
        return None

    # Si es un diccionario de Podio
    if isinstance(value, dict):
        # Podio puede devolver varios formatos
        date_str = value.get("start_date") or value.get(
            "start_utc") or value.get("start")
    else:
        date_str = value

    if not date_str:
        return None

    # Solo quedarnos con la parte de fecha
    if " " in date_str:
        date_str = date_str.split(" ")[0]

    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def clean_html(value: Optional[str]) -> Optional[str]:

    # Elimina etiquetas HTML y espacios innecesarios.
    if not value:
        return None
    return re.sub(r"<.*?>", "", str(value)).strip()
