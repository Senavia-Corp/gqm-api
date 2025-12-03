
from sqlmodel import SQLModel
from sqlalchemy.inspection import inspect


def add_relationships(obj, relations: list[str]):

    SENSITIVE_FIELDS = {"Password", "password", "hashed_password", "pass"}

    # -----------------------------
    # 1️. Base model_dump
    # -----------------------------
    base = obj.model_dump()
    mapper = inspect(obj.__class__)

    # -----------------------------
    # 2️. Procesar relaciones planas para quitar FKs
    # -----------------------------
    top_level_rels = {r.split(".")[0] for r in relations}
    fks_to_remove = []

    for rel_name in top_level_rels:
        if rel_name in mapper.relationships:
            rel = mapper.relationships[rel_name]

            if rel.secondary is not None:
                continue  # Many-to-Many → no tocar FKs

            for fk_col in rel.local_columns:
                if not fk_col.primary_key:
                    fks_to_remove.append(fk_col.key)

    for fk in fks_to_remove:
        base.pop(fk, None)

    # -----------------------------
    # 3️. Función recursiva para expandir relaciones
    # -----------------------------
    def expand(obj, rel_path: list[str]):
        current_rel = rel_path[0]
        rel_obj = getattr(obj, current_rel, None)

        if rel_obj is None:
            return None

        if isinstance(rel_obj, list):
            items = []
            for item in rel_obj:
                item_data = item.model_dump()
                if len(rel_path) > 1:
                    child = expand(item, rel_path[1:])
                    if child is not None:
                        item_data[rel_path[1]] = child
                items.append(item_data)
            return items

        item_data = rel_obj.model_dump()
        if len(rel_path) > 1:
            child = expand(rel_obj, rel_path[1:])
            if child is not None:
                item_data[rel_path[1]] = child

        return item_data

    # Construir las relaciones en base
    for rel in relations:
        rel_path = rel.split(".")
        expanded = expand(obj, rel_path)
        base[rel_path[0]] = expanded

    # -----------------------------
    # 4️. Limpiar campos sensibles recursivamente
    # -----------------------------
    def remove_sensitive(data):
        if isinstance(data, dict):
            return {k: remove_sensitive(v) for k, v in data.items() if k not in SENSITIVE_FIELDS}
        if isinstance(data, list):
            return [remove_sensitive(i) for i in data]
        return data

    return remove_sensitive(base)
