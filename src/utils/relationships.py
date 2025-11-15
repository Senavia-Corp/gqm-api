
from sqlalchemy.inspection import inspect


def add_relationships(obj, relations: list[str]):
    """
    Convierte un SQLModel a dict y agrega relaciones anidadas.
    """

    base = obj.model_dump()

    # Inspeccionar el mapper SQLAlchemy del modelo
    mapper = inspect(obj.__class__)

    # Detectar FKs correspondientes a las relaciones incluidas
    fks_to_remove = []

    for rel_name in relations:
        if rel_name in mapper.relationships:
            rel = mapper.relationships[rel_name]

            # Obtener columnas FK locales que apuntan a esta relación
            for fk_col in rel.local_columns:
                fks_to_remove.append(fk_col.key)

    # Eliminar automáticamente todas las FKs detectadas
    for fk in fks_to_remove:
        base.pop(fk, None)

    # Agregar las relaciones anidadas
    for rel_name in relations:
        rel_obj = getattr(obj, rel_name, None)
        base[rel_name] = rel_obj.model_dump() if rel_obj else None

    return base
