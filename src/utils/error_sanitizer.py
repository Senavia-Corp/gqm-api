def sanitize_error(err) -> str:
    """Resumen seguro de una excepción para persistir en tablas consultables
    (p.ej. podio_failed_syncs): clase + primera línea, cortando los volcados
    de SQLAlchemy con sentencia/parámetros. El detalle completo va a logs.
    """
    if isinstance(err, BaseException):
        name = type(err).__name__
        text = str(err)
    else:
        name = "Error"
        text = str(err or "")

    first = text.splitlines()[0] if text else ""
    for marker in ("[SQL:", "[parameters:"):
        idx = first.find(marker)
        if idx != -1:
            first = first[:idx]
    return f"{name}: {first[:300]}".strip()
