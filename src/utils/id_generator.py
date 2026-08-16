from datetime import datetime
from sqlmodel import select


def generate_custom_id(session, model, id_field_name: str, prefix: str) -> str:

    # Genera un ID único con formato: PREFIX + último_dígito_año + contador
    # Ejemplo: SUP50001 → SUP (prefijo), 5 (año 2025), 0001 (contador)
    #
    # El contador arranca con 4 cifras pero NO está limitado a 4: al pasar de
    # 9999 crece a 5 (…10000). Ese desbordamiento es justo lo que rompía la
    # versión anterior, que buscaba el último ID con `ORDER BY id DESC`, es
    # decir en orden LEXICOGRÁFICO:
    #
    #     "TLA69999"  >  "TLA610000"      ← como texto, '9' > '1'
    #
    # Así que una vez existía TLA610000 el generador seguía viendo TLA69999
    # como "el último", calculaba 9999+1 y devolvía un ID YA EXISTENTE. En
    # producción eso dejó `tlactivity` sin escribir desde el 20-may-2026: el
    # IntegrityError lo absorbe el `except` de log_activity y falla en
    # silencio. Medido el 16-ago-2026: 9 736 filas TLA6xxxx + 1 sola TLA610000,
    # que es la última fila registrada. 88 días de auditoría perdidos.
    #
    # `order` iba camino de lo mismo (ORD69707 de 9999), pero ahí el fallo no
    # es silencioso: reventaría el alta con clave duplicada.
    #
    # Por eso el máximo se calcula por el SUFIJO NUMÉRICO, no por el texto.

    current_year = datetime.now().year
    year_digit = str(current_year)[-1]  # último dígito del año

    id_column = getattr(model, id_field_name)

    # ponytail: trae la columna de IDs del año en curso y saca el máximo en
    # Python. Es O(n) pero n es el nº de filas del año (≈10 k como mucho) y una
    # sola columna varchar. Si algún día molesta, el paso siguiente es una
    # secuencia de Postgres por prefijo — no un ORDER BY más listo, que es
    # justo lo que fallaba.
    ids = session.exec(
        select(id_column).where(id_column.like(f"{prefix}{year_digit}%"))
    ).all()

    corte = len(prefix) + 1  # salta el prefijo y el dígito del año
    ultimo = 0
    for valor in ids:
        # Los IDs legacy sin sufijo numérico (p. ej. "BLGDEP6") se ignoran en
        # vez de reiniciar el contador a 1, que colisionaría con los ya usados.
        try:
            ultimo = max(ultimo, int(valor[corte:]))
        except (ValueError, TypeError, IndexError):
            continue

    next_num = ultimo + 1

    # `:04` rellena hasta 4 cifras, pero NO trunca: 10000 sale como "10000".
    return f"{prefix}{year_digit}{next_num:04}"
