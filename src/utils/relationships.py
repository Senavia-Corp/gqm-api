
from sqlmodel import SQLModel
from sqlalchemy.inspection import inspect


def add_relationships(obj, relations: list[str]):
    SENSITIVE_FIELDS = {"Password", "password", "hashed_password", "pass"}

    base = obj.model_dump()
    mapper = inspect(obj.__class__)

    top_level_rels = {r.split(".")[0] for r in relations}
    fks_to_remove = []

    for rel_name in top_level_rels:
        if rel_name in mapper.relationships:
            rel = mapper.relationships[rel_name]
            if rel.secondary is not None:
                continue
            for fk_col in rel.local_columns:
                if not fk_col.primary_key:
                    fks_to_remove.append(fk_col.key)

    for fk in fks_to_remove:
        base.pop(fk, None)

    # -----------------------------
    # RECURSIVA DE EXPANSIÓN
    # -----------------------------
    def expand(obj, rel_path: list[str]):
        current_rel = rel_path[0]
        rel_obj = getattr(obj, current_rel, None)

        if rel_obj is None:
            return None

        # Lista → procesar cada ítem
        if isinstance(rel_obj, list):
            items = []
            for item in rel_obj:
                item_data = item.model_dump()
                # expandir niveles hijos
                if len(rel_path) > 1:
                    child_key = rel_path[1]
                    child = expand(item, rel_path[1:])
                    if child is not None:
                        item_data[child_key] = child
                items.append(item_data)
            return items

        # Objeto simple
        item_data = rel_obj.model_dump()
        if len(rel_path) > 1:
            child_key = rel_path[1]
            child = expand(rel_obj, rel_path[1:])
            if child is not None:
                item_data[child_key] = child

        return item_data

    # -----------------------------
    # MERGEAR MULTIPLES SUBRUTAS
    # -----------------------------
    temp_store = {}

    for rel in relations:
        rel_path = rel.split(".")
        root = rel_path[0]
        expanded = expand(obj, rel_path)

        if root not in temp_store:
            temp_store[root] = expanded
        else:
            # fusiona listas de subcontractors
            if isinstance(temp_store[root], list) and isinstance(expanded, list):
                for i in range(len(temp_store[root])):
                    if isinstance(temp_store[root][i], dict) and isinstance(expanded[i], dict):
                        temp_store[root][i].update(expanded[i])

            # fusiona dicts simples
            elif isinstance(temp_store[root], dict) and isinstance(expanded, dict):
                temp_store[root].update(expanded)

    # agregar los resultados fusionados al base
    for k, v in temp_store.items():
        base[k] = v

    # -----------------------------
    # SENSITIVE FIELD CLEANUP
    # -----------------------------
    def remove_sensitive(data):
        if isinstance(data, dict):
            return {k: remove_sensitive(v) for k, v in data.items() if k not in SENSITIVE_FIELDS}
        if isinstance(data, list):
            return [remove_sensitive(i) for i in data]
        return data

    return remove_sensitive(base)
