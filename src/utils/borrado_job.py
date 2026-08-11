"""Borrar un job sin dejar huérfanos.

Ninguna tabla hija declara `ondelete` en la BD (solo `tasks`), así que la
limpieza depende de lo que el ORM tenga configurado, y está a medias:

- **Cascadean** (`delete-orphan` en `JobModel.py:102-127`): attachments, tasks,
  estimate_costs, tlactivity, chat_messages, commission_detail.
- **No cascadean**: purchases, opportunities, change_orders, financial_docs.
  Para esas, SQLAlchemy no falla ni borra: pone la FK a **NULL**. La fila queda
  flotando, sin dueño y sin ruido.

Eso no es teórico. En producción hoy hay 9 purchases, 8 change_orders y 31
financial_documents con `ID_Jobs IS NULL`: es la huella de los borrados que ya
se hicieron. Por eso `sentinela_huerfanos` se mide **antes y después** de cada
borrado y tiene que salir idéntica; si sube, el borrado corrompió algo.
"""
from sqlalchemy import func, select

# (etiqueta, tabla, columna de enlace, cascadea?)
# El orden es el del artefacto del dry-run, así que se lee de mayor a menor
# riesgo: primero lo que se queda huérfano, luego lo que desaparece.
TABLAS_HIJAS = [
    ("purchase", "purchase", "ID_Jobs", False),
    ("opportunities", "opportunities", "ID_Jobs", False),
    ("change_order", "change_order", "ID_Jobs", False),
    ("financial_document", "financial_document", "ID_Jobs", False),
    ("estimate_cost", "estimate_cost", "ID_Jobs", True),
    ("attachments", "attachments", "ID_Jobs", True),
    ("tasks", "tasks", "ID_Jobs", True),
    ("tlactivity", "tlactivity", "ID_Jobs", True),
    ("commission_detail", "commission_detail", "ID_Jobs", True),
    # OJO: singular. `chat_message` es la única hija que no usa "ID_Jobs".
    ("chat_message", "chat_message", "ID_Job", True),
]

# Las cuatro que se quedan con la FK a NULL en vez de borrarse.
SIN_CASCADE = [t for t in TABLAS_HIJAS if not t[3]]


def _cuenta(session, tabla: str, columna: str, valor) -> int:
    from sqlalchemy import text
    return session.exec(
        text(f'SELECT count(*) FROM {tabla} WHERE "{columna}" = :v').bindparams(v=valor)
    ).scalar() or 0


def inventario_dependientes(session, job) -> dict:
    """Qué arrastra este job. Es el artefacto del dry-run.

    Se cuenta TODO, incluido lo que cascadea: `chat_message` desaparece en
    silencio con el job y nadie lo esperaría si no estuviera en la lista.
    """
    por_tabla, total = {}, 0
    for etiqueta, tabla, columna, cascadea in TABLAS_HIJAS:
        try:
            n = _cuenta(session, tabla, columna, job.ID_Jobs)
        except Exception as e:  # una tabla que no exista no puede tumbar el dry-run
            por_tabla[etiqueta] = {"error": f"{type(e).__name__}: {e}"}
            continue
        if n:
            por_tabla[etiqueta] = {"filas": n, "cascadea": cascadea}
            total += n

    return {
        "ID_Jobs": job.ID_Jobs,
        "Job_type": job.Job_type,
        "Job_status": job.Job_status,
        "Project_name": job.Project_name,
        "podio_item_id": job.podio_item_id,
        "podio_app_year": job.podio_app_year,
        "dependientes": por_tabla,
        "total_dependientes": total,
        "quedarian_huerfanos": sum(
            v.get("filas", 0) for k, v in por_tabla.items()
            if not v.get("cascadea", True)),
    }


def sentinela_huerfanos(session) -> dict:
    """Filas con `ID_Jobs` NULL en las 4 tablas que no cascadean.

    Se compara antes/después de borrar: si sube, el borrado dejó huérfanos.
    Baseline medido en producción el 10-ago-2026:
    purchase 9 · opportunities 0 · change_order 8 · financial_document 31.
    """
    from sqlalchemy import text

    conteo = {}
    for etiqueta, tabla, columna, _ in SIN_CASCADE:
        conteo[etiqueta] = session.exec(
            text(f'SELECT count(*) FROM {tabla} WHERE "{columna}" IS NULL')
        ).scalar() or 0
    return conteo


class HuerfanosCreados(Exception):
    """El borrado dejó filas sin dueño. Hay que revertir."""


def desvincular_sin_cascade(session, job) -> dict:
    """Borra explícitamente las hijas que el ORM dejaría con la FK a NULL.

    Es la decisión que hoy está tomando el default de SQLAlchemy sin que nadie
    la haya tomado: purchases y opportunities son hijas del job, no entidades
    independientes, así que se van con él.
    """
    from sqlalchemy import text

    borradas = {}
    for etiqueta, tabla, columna, _ in SIN_CASCADE:
        res = session.exec(
            text(f'DELETE FROM {tabla} WHERE "{columna}" = :v').bindparams(
                v=job.ID_Jobs))
        if res.rowcount:
            borradas[etiqueta] = res.rowcount
    return borradas


def borrar_job_sin_huerfanos(session, job) -> dict:
    """Borra el job y **verifica** que no dejó nada flotando.

    La aserción es el punto entero de esta función: sin ella el borrado parece
    limpio porque no lanza nada, y las huérfanas solo aparecen meses después
    cuando alguien cuenta filas con `ID_Jobs IS NULL`.
    """
    antes = sentinela_huerfanos(session)
    inventario = inventario_dependientes(session, job)

    borradas = desvincular_sin_cascade(session, job)
    session.delete(job)   # el resto cae por cascade del ORM
    session.flush()

    despues = sentinela_huerfanos(session)
    if despues != antes:
        raise HuerfanosCreados(
            f"el borrado de {inventario['ID_Jobs']} dejó huérfanos: "
            f"antes {antes}, después {despues}"
        )

    return {"inventario": inventario, "borradas_sin_cascade": borradas,
            "huerfanos": {"antes": antes, "despues": despues}}
