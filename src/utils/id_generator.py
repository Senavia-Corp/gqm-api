from datetime import datetime
from sqlmodel import select


def generate_custom_id(session, model, id_field_name: str, prefix: str) -> str:

    # Genera un ID único con formato: PREFIX + número secuencial (3 dígitos) + año actual.

    # Obtener la columna dinámicamente (por nombre)
    id_column = getattr(model, id_field_name)

    # Buscar el último registro con el prefijo
    statement = (
        select(model)
        .where(id_column.like(f"{prefix}%"))
        .order_by(id_column.desc())
    )
    last_entry = session.exec(statement).first()

    # Calcular el siguiente número
    if last_entry:
        last_id = getattr(last_entry, id_field_name)
        # Ejemplo: SUP0012025 → toma "001"
        last_num = int(last_id[len(prefix):len(prefix) + 3])
        next_num = last_num + 1
    else:
        next_num = 1

    # Formar nuevo ID (SUP0012025)
    new_id = f"{prefix}{next_num:03}{datetime.now().year}"
    return new_id
