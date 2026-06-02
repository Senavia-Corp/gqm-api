from datetime import date, datetime, timedelta
from decimal import Decimal


def convert_value_for_podio(value, field_type="text", end_value=None, with_time=False):

    if field_type == "app":
        # Podio espera lista: [{"value": item_id}]
        return [{"value": int(value)}] if value else []

    if field_type == "tag":
        # Podio espera lista de strings
        if not value:
            return []
        # Aseguramos que siempre sea lista
        if isinstance(value, str):
            return [value]
        elif isinstance(value, list):
            # Convertimos todos los elementos a string
            return [str(v) for v in value if v is not None]
        else:
            # Si viene algo raro, lo convertimos a string en una lista
            return [str(value)]

    if field_type == "text":
        return {"value": str(value)} if value is not None else None

    if field_type == "category":
        if not value:
            return []
        # Si es string simple, lo convertimos en lista
        if isinstance(value, str):
            return [{"value": value}]
        elif isinstance(value, list):
            return [{"value": str(v)} for v in value if v is not None]
        else:
            # Si viene algo raro, lo convertimos a un valor único
            return [{"value": str(value)}]

    if field_type == "embed":
        if value is None:
            return None

        def normalize_url(url: str):
            url = url.strip()
            if not url:
                return None

            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            return {"url": url}

        # Caso 1: string directo
        if isinstance(value, str):
            return normalize_url(value)

        # Caso 2: dict {"url": "..."}
        if isinstance(value, dict) and "url" in value:
            return normalize_url(str(value.get("url")))

    if field_type == "number":
        if value is None:
            return None
        return {"value": float(value)}

    if field_type == "progress":
        if value is None:
            return None
        value_int = int(value)
        if not (0 <= value_int <= 100):
            raise ValueError("Progress must be between 0 and 100.")
        return {"value": value_int}

    if field_type == "date":
        if value is None:
            return None

        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day, 0, 0, 0)

        if not isinstance(value, (datetime, date)):
            raise ValueError("Date fields must be datetime or date.")

        # Helper to avoid Podio's 00:00:00 truncation bug
        def format_podio_date(dt_val: datetime) -> str:
            if with_time:
                if dt_val.hour == 0 and dt_val.minute == 0 and dt_val.second == 0:
                    # Use noon instead of midnight to guarantee Podio registers it as "with time"
                    dt_val = dt_val.replace(hour=12, minute=0, second=0)
                return dt_val.strftime("%Y-%m-%d %H:%M:%S")
            else:
                # Podio API requires HH:MM:SS format even for time-disabled fields, but it MUST be 00:00:00
                dt_val = dt_val.replace(hour=0, minute=0, second=0)
                return dt_val.strftime("%Y-%m-%d %H:%M:%S")

        formatted_start = format_podio_date(value)
        
        payload = {"start": formatted_start}

        if end_value is not None:
            if isinstance(end_value, date) and not isinstance(end_value, datetime):
                end_value = datetime(end_value.year, end_value.month, end_value.day, 0, 0, 0)
            payload["end"] = format_podio_date(end_value)
        
        return payload

    if field_type == "email":
        if not value:
            return []
        if isinstance(value, str):
            return [{"type": "work", "value": value}]
        if isinstance(value, list):
            return [{"type": "work", "value": str(v)} for v in value if v]
        return []

    if field_type == "phone":
        if not value:
            return []
        if isinstance(value, str):
            return [{"type": "work", "value": value}]
        if isinstance(value, list):
            return [{"type": "work", "value": str(v)} for v in value if v]
        return []

    if field_type == "contact":
        if not value:
            return []
        if isinstance(value, list):
            return [{"value": int(v)} for v in value]
        return [{"value": int(value)}]  # profile_id

    if field_type == "location":
        if value is None:
            return None
        return {"value": str(value)}

    if field_type == "money":
        if value is None:
            return None
        #   {"value": 100, "currency": "EUR"}
        if isinstance(value, dict):
            return {
                "value": str(Decimal(value["value"])),
                "currency": value.get("currency", "USD")
            }

        return {
            "value": str(Decimal(value)),
            "currency": "USD"
        }

    if field_type == "calculation":
        if value is None:
            return None

        # Podio *ignora* el valor, pero no rompe si lo envías
        return {"value": float(value)}

    # Default (fallback)
    return {"value": value}
