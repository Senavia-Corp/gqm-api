from datetime import date, datetime


def clean_podio_fields(fields: dict) -> dict:
    """
    Elimina valores vacíos o None, convierte números a string
    y convierte fechas a formato ISO para que Podio las acepte.
    """
    cleaned = {}

    for k, v in fields.items():
        # Ignorar campos vacíos
        if v == []:
            cleaned[k] = v
            continue

        # Ignorar los demás valores vacíos
        if v in [None, "", {}]:
            continue

        # Convertir fechas a string ISO
        if isinstance(v, (date, datetime)):
            cleaned[k] = v.isoformat()
            continue

        # Convertir números a string
        if isinstance(v, (int, float)):
            cleaned[k] = str(v)
            continue

        # Mantener el valor tal cual para strings u otros tipos
        cleaned[k] = v

    return cleaned
