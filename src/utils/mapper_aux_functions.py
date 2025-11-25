from typing import Optional
from datetime import datetime
import re


def parse_date(value: Optional[str]) -> Optional[datetime.date]:

    # Convierte string de Podio a datetime.date.
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def clean_html(value: Optional[str]) -> Optional[str]:

    # Elimina etiquetas HTML y espacios innecesarios.
    if not value:
        return None
    return re.sub(r"<.*?>", "", str(value)).strip()
