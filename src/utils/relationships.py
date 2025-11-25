
from sqlalchemy.inspection import inspect


def add_relationships(obj, relations: list[str]):
    base = obj.model_dump()

    mapper = inspect(obj.__class__)
    fks_to_remove = []

    for rel_name in relations:
        if rel_name in mapper.relationships:
            rel = mapper.relationships[rel_name]

            # Si es Many-to-Many → NO eliminar FKs
            if rel.secondary is not None:
                continue

            # Si es One-to-Many o Many-to-One → eliminar FKs
            for fk_col in rel.local_columns:
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
