"""La tabla «P/Quote Pipeline per Member» mostraba de todo menos P/Quote.

`jobs_member_pipeline` filtraba por `PENDING_ALL`, la union aplanada de los
buckets pendientes de los tres tipos, y encima con un `IN (...)` plano que no
empareja estado con tipo de job. Medido en produccion el 22-ago-2026: de las
1.843 filas que salian, **1.697 eran `Waiting for Approval` y 93 `HOLD`**, y solo
52 el `Assigned/P. Quote` que da nombre a la seccion. La captura del cliente
mostraba a Francis Lopez con «105 jobs / $513.4k»; la consulta equivalente al
codigo viejo devolvia exactamente 105 jobs / $513.359.

El segundo defecto era la atribucion: se unia `job_member` por `Acc Rep Selling`
Y `Mgmt Member` a la vez, asi que un job con los dos roles aparecia bajo dos
miembros distintos y la suma de la tabla no era el pipeline (Paola Colman: 658
filas para 553 jobs).

Estos tests son ESTRUCTURALES: miran el SQL compilado, no los datos. Corren sin
`.env` y sin base de datos porque solo importan `metrics_shared` y los modelos:

    .venv/bin/python -m pytest --noconftest tests/unit/test_member_pipeline_estados.py -q

El `--noconftest` es obligatorio: `tests/conftest.py` hace `sys.exit` si
`DATABASE_URL` no apunta a Neon develop, y eso mata la sesion entera.
"""
from src.services.metrics.metrics_shared import (
    PENDING_ALL,
    QUOTE_OWNER_ROLE_PREFERENCE,
    QUOTE_PIPELINE_BY_TYPE,
    quote_owner_id_expr,
    universo_cotizaciones,
)

# Los dos estados que inflaban la tabla y que NO son «por cotizar».
ESTADOS_QUE_NO_SON_PQUOTE = ("Waiting for Approval", "HOLD", "Hold")


def _sql(expresion) -> str:
    return str(expresion.compile(compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# Los estados por tipo
# ---------------------------------------------------------------------------

def test_qid_solo_admite_el_estado_que_da_nombre_a_la_seccion():
    assert QUOTE_PIPELINE_BY_TYPE["QID"] == {"Assigned/P. Quote"}, (
        f"QID deberia traer solo el estado del titulo, trae "
        f"{sorted(QUOTE_PIPELINE_BY_TYPE['QID'])}"
    )


def test_ptl_solo_admite_received_stand_by():
    assert QUOTE_PIPELINE_BY_TYPE["PTL"] == {"Received-Stand By"}, (
        "PTL solo tiene una etapa antes de asignar tecnico"
    )


def test_par_no_tiene_etapa_de_cotizacion():
    assert QUOTE_PIPELINE_BY_TYPE["PAR"] == set(), (
        "PAR nace aprobado y entra en In Progress: no hay nada que cotizar"
    )
    assert quote_owner_id_expr("PAR") is None, (
        "sin etapa de cotizacion no hay dueno que calcular, y el endpoint tiene "
        "que cortar antes de ir a la BD"
    )


def test_los_estados_que_inflaban_la_tabla_quedan_fuera():
    todos = set().union(*QUOTE_PIPELINE_BY_TYPE.values())
    for estado in ESTADOS_QUE_NO_SON_PQUOTE:
        assert estado not in todos, (
            f"«{estado}» volvio a entrar en el pipeline de cotizaciones; es "
            f"justo lo que hacia que la seccion mostrase 1.843 filas"
        )


def test_no_se_toco_el_bucket_compartido_de_pendientes():
    """Guarda de radio de impacto.

    `PENDING_ALL` lo consumen los KPIs de Communities, Clients y Parent
    Companies. Esta seccion tenia que dejar de usarlo, no cambiarlo: si alguien
    «limpia» esa constante para que encaje aqui, mueve KPIs de otras pestanas.
    """
    for estado in ESTADOS_QUE_NO_SON_PQUOTE:
        assert estado in PENDING_ALL, (
            f"«{estado}» desaparecio de PENDING_ALL — eso mueve los KPIs de "
            f"Communities/Clients/Parent Companies, que no son de esta tarea"
        )


# ---------------------------------------------------------------------------
# El dueno de la cotizacion
# ---------------------------------------------------------------------------

def test_el_pm_solo_cubre_el_hueco_cuando_no_hay_acc_rep():
    assert QUOTE_OWNER_ROLE_PREFERENCE["QID"] == ["Acc Rep Selling", "Mgmt Member"], (
        "el orden ES la regla: el vendedor manda y el PM solo rellena"
    )
    sql = _sql(quote_owner_id_expr("QID"))
    assert "coalesce" in sql.lower(), "la preferencia se expresa con COALESCE"
    assert sql.index("Acc Rep Selling") < sql.index("Mgmt Member"), (
        "el Acc Rep tiene que evaluarse ANTES que el Mgmt Member, o el PM se "
        "queda las cotizaciones del vendedor"
    )


def test_el_dueno_es_determinista_aunque_haya_dos_del_mismo_rol():
    """En produccion hay 15 jobs con dos `Acc Rep Selling` y 25 con dos `Mgmt
    Member`. Con `LIMIT 1` el dueno cambiaria entre ejecuciones."""
    sql = _sql(quote_owner_id_expr("QID"))
    assert "min(" in sql.lower(), "sin min() el dueno seria arbitrario"
    assert "limit" not in sql.lower(), (
        "un LIMIT sin ORDER BY hace que el dueno dependa del plan de ejecucion"
    )


# ---------------------------------------------------------------------------
# El universo de cotizaciones
# ---------------------------------------------------------------------------

def test_cada_tipo_se_empareja_con_sus_propios_estados():
    """El bug original: `Job_status.in_(PENDING_ALL)` sin mirar `Job_type`.

    En produccion hay contaminacion real entre catalogos (2 PTL y 12 PAR con
    `Scheduled / Work in Progress`, que es un estado de QID), asi que el
    emparejamiento no es teorico.
    """
    sql = _sql(universo_cotizaciones(["QID", "PTL"]))
    assert "'QID' AND" in sql and "'PTL' AND" in sql, (
        "cada rama tiene que filtrar por su tipo antes que por el estado"
    )
    for estado in ESTADOS_QUE_NO_SON_PQUOTE:
        assert estado not in sql, f"«{estado}» aparece en el SQL del universo"


def test_un_job_no_puede_repetirse_bajo_un_miembro():
    """Lo que sustituye al dedup manual que habia en Python.

    Los roles se resuelven en subconsultas correlacionadas, no con un JOIN a
    `job_member` en el FROM. Sin ese JOIN, un job produce como mucho una fila
    por tipo, asi que la duplicacion es imposible por construccion.
    """
    sql = _sql(universo_cotizaciones(["QID"]))
    cabecera = sql.split("WHERE")[0]
    assert "join" not in cabecera.lower(), (
        "un JOIN a job_member en el FROM devuelve una fila por rol y reintroduce "
        "el job duplicado que el dedup tapaba"
    )


def test_el_filtro_de_anio_usa_el_ano_de_app_y_ninguna_fecha():
    sql = _sql(universo_cotizaciones(["QID", "PTL"], 2026))
    assert "podio_app_year" in sql, "el ano es la app de Podio, no una fecha"
    for columna in ("Date_assigned", "Estimated_start_date"):
        assert columna not in sql, (
            f"el filtro de ano volvio a mirar {columna}: eso perdia 43 jobs no "
            f"cancelados que salian en «All» y en ningun ano"
        )


def test_sin_anio_no_se_filtra_por_anio():
    assert "podio_app_year" not in _sql(universo_cotizaciones(["QID"])), (
        "sin parametro `year` la vista es de todos los anos"
    )
