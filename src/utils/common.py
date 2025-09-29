class PodioError(Exception):
    """Error de integración con Podio."""
    pass


def prune_nulls(obj, drop_empty=False):
    """
    Elimina recursivamente:
      - claves con valor None en dicts
      - elementos None en listas
    Si drop_empty=True, también elimina dicts/listas vacíos.
    Mantiene 0/False/'': no se consideran null.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if v is None:
                continue
            v2 = prune_nulls(v, drop_empty=drop_empty)
            if drop_empty and (v2 == {} or v2 == []):
                continue
            out[k] = v2
        return out
    if isinstance(obj, list):
        out = [prune_nulls(v, drop_empty=drop_empty) for v in obj if v is not None]
        if drop_empty:
            out = [v for v in out if not (v == {} or v == [])]
        return out
    return obj