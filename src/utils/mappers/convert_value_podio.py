from datetime import date, datetime
from decimal import Decimal


def convert_value_for_podio(value, field_type="text"):

    if field_type == "app":
        return {"value": int(value)} if value else None

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

        formatted = value.strftime("%Y-%m-%d %H:%M:%S")

        return {
            "start": formatted,
            "end": formatted
        }

    if field_type == "email":
        if value is None:
            return None
        return [{"type": "work", "value": str(value)}]

    if field_type == "phone":
        if value is None:
            return None
        return [{"type": "work", "value": str(value)}]

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
