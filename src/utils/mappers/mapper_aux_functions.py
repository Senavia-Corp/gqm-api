import time
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


def has_html(text: str) -> bool:
    """
    Detecta si un texto contiene HTML
    """
    return "<" in text and ">" in text


def clean_html(value: Optional[str]) -> Optional[str]:
    """
    Limpia HTML preservando saltos de línea entre párrafos
    """
    if not value:
        return None

    text = str(value)

    # Convertir párrafos y <br> en saltos de línea
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # Eliminar cualquier otra etiqueta HTML
    text = re.sub(r"<.*?>", "", text)

    # Limpiar espacios
    return text.strip()


# Para ignorar el webhook si el evento es local:
recent_events = {}

# Tiempo de expiración para ignorar webhooks recientes (en segundos)
ANTI_LOOP_WINDOW = 15


def is_recent_event(item_id):
    item_id_str = str(item_id)
    ts = recent_events.get(item_id_str)
    if ts and (time.time() - ts < ANTI_LOOP_WINDOW):
        print(f"⛔ Ignorando webhook (evento reciente): {item_id_str}")
        return True
    return False


def register_event(item_id):
    recent_events[str(item_id)] = time.time()
