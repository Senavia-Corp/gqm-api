def clean_podio_fields(fields: dict) -> dict:
    """
    Elimina valores vacíos o None y convierte números a string,
    para evitar errores 400 de Podio.
    """
    cleaned = {
        k: v for k, v in fields.items()
        if v not in [None, "", [], {}]
    }
    return {
        k: str(v) if isinstance(v, (int, float)) else v
        for k, v in cleaned.items()
    }
