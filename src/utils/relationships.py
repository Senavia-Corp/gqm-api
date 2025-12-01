
from sqlalchemy.inspection import inspect


def add_relationships(obj, relations: list[str]):
    base = obj.model_dump()

    mapper = inspect(obj.__class__)
    fks_to_remove = []

    for rel_name in relations:
        if rel_name in mapper.relationships:
            rel = mapper.relationships[rel_name]

            # Many-to-Many → no tocar FKs
            if rel.secondary is not None:
                continue

            # One-to-Many o Many-to-One → eliminar solo FKs que NO sean PK
            for fk_col in rel.local_columns:
                if not fk_col.primary_key:   # ⬅⬅⬅ FIX
                    fks_to_remove.append(fk_col.key)

    for fk in fks_to_remove:
        base.pop(fk, None)

    for rel_name in relations:
        rel_obj = getattr(obj, rel_name, None)

        if isinstance(rel_obj, list):
            base[rel_name] = [item.model_dump() for item in rel_obj]
        else:
            base[rel_name] = rel_obj.model_dump() if rel_obj else None

    return base
