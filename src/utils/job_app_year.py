"""Una sola regla para saber a qué app-año de Podio pertenece un job.

Había ocho reglas distintas repartidas por el código y solo una funciona: el
dígito del año va **dentro del propio `ID_Jobs`**, que es el contador nativo de
Podio y por tanto la única fuente que no se puede desincronizar.

    QID50001    → 2025
    QID-I60001  → 2026     (los 7 jobs locales: el 4.º carácter es '-')
    QID80001    → None     (8 no es un año configurado; jobs sembrados por tests)

Ojo con el formato: **no** es «el 4.º carácter». Los jobs locales creados con
`sync_podio=false` llevan `-I` entre el prefijo y el número, así que la regla es
quitar el prefijo de 3 letras y tomar el **primer dígito del resto**.

Lo que esta regla NO usa, y por qué:

- `Date_assigned` — el 100 % de los PTL lo tienen NULL, así que deja sin año a
  los 510 PTL de producción; y donde sí existe, discrepa del año de la app en 88
  jobs, 56 de ellos hacia 2022, un año que `get_job_app_credentials` ni siquiera
  tiene configurado.
- `now()` — adivinar el año manda el update a la app equivocada (REG-015).

Tres consumidores comparten esta regla y `tests/unit/test_regla_anio_unica.py`
los compara entre sí: Python (`anio_desde_id_jobs`), SQL de migración
(`SQL_ANIO_DESDE_ID`) y expresión de consulta (`expr_anio_app`).
"""
from sqlalchemy import Integer, case, cast, func

# 3→2023 … 6→2026. Deliberadamente NO se deriva de JOB_YEARS: esto describe
# cómo Podio numera sus IDs, no qué apps hay configuradas hoy.
DIGITO_A_ANIO = {"3": 2023, "4": 2024, "5": 2025, "6": 2026}

LARGO_PREFIJO = 3  # QID / PTL / PAR

# El mismo cálculo en SQL, para que la migración y las consultas no puedan
# discrepar. `substring(texto, patron)` es la forma regex de Postgres.
SQL_DIGITO = """substring(substring({col} from {desde}) from '[0-9]')"""
SQL_ANIO_DESDE_ID = """
CASE WHEN {digito} IN ('3','4','5','6')
     THEN 2020 + ({digito})::int
END
""".strip()


def sql_anio_desde_id(col: str = '"ID_Jobs"') -> str:
    """El fragmento SQL de la regla, para migraciones."""
    digito = SQL_DIGITO.format(col=col, desde=LARGO_PREFIJO + 1)
    return SQL_ANIO_DESDE_ID.format(digito=digito)


def anio_desde_id_jobs(id_jobs) -> int | None:
    """Primer dígito después del prefijo de 3 letras, mapeado a año."""
    if not id_jobs:
        return None
    texto = str(id_jobs)
    if len(texto) <= LARGO_PREFIJO or not texto[:LARGO_PREFIJO].isalpha():
        return None
    for caracter in texto[LARGO_PREFIJO:]:
        if caracter.isdigit():
            return DIGITO_A_ANIO.get(caracter)
    return None


def resolver_anio_app(job) -> int | None:
    """El año persistido si lo hay; si no, el derivado de `ID_Jobs`.

    `is not None` y no truthiness: un 0 persistido debe verse como dato malo,
    no colarse silenciosamente al fallback.
    """
    persistido = getattr(job, "podio_app_year", None)
    if persistido is not None:
        return persistido
    return anio_desde_id_jobs(getattr(job, "ID_Jobs", None))


def expr_anio_app():
    """La misma regla como expresión SQLAlchemy, para filtrar y contar.

    Va con `coalesce` a propósito: la columna `podio_app_year` está NULL para
    todos los PTL (el backfill viejo usó `Date_assigned`) y para los jobs
    locales. Filtrar por la columna pelada los haría desaparecer del panel.
    """
    from src.models.JobModel import Job

    digito = func.substring(func.substring(Job.ID_Jobs, LARGO_PREFIJO + 1), "[0-9]")
    return func.coalesce(
        Job.podio_app_year,
        case((digito.in_(tuple(DIGITO_A_ANIO)), cast(digito, Integer) + 2020),
             else_=None),
    )
