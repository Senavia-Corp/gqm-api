from datetime import datetime
from sqlmodel import select


def generate_custom_id(session, model, id_field_name: str, prefix: str) -> str:

    # Genera un ID único con formato: PREFIX + último_dígito_año + número secuencial (4 dígitos)
    # Ejemplo: SUP50001 → SUP (prefijo), 5 (año 2025), 0001 (contador)

    current_year = datetime.now().year
    year_digit = str(current_year)[-1]  # último dígito del año

    id_column = getattr(model, id_field_name)

    # Buscar el último registro con el prefijo y el dígito del año actual
    statement = (
        select(model)
        .where(id_column.like(f"{prefix}{year_digit}%"))
        .order_by(id_column.desc())
    )
    last_entry = session.exec(statement).first()

    # Calcular el siguiente número
    if last_entry:
        last_id = getattr(last_entry, id_field_name)
        # Ejemplo: SUP50001 → extrae "0001"
        # después del prefijo y del dígito del año
        last_num = int(last_id[len(prefix) + 1:])
        next_num = last_num + 1
    else:
        next_num = 1

    # Formar nuevo ID (ejemplo: SUP50001)
    new_id = f"{prefix}{year_digit}{next_num:04}"
    return new_id
