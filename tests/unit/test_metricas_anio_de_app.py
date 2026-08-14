"""Las métricas tienen que filtrar por el año de la app, igual que /jobs/.

El defecto que este test existe para evitar: `_apply_year_filter` derivaba el año
de columnas de fecha (`Estimated_start_date` para PTL, `Date_assigned` para el
resto) **con guardas `IS NOT NULL`**, mientras `/jobs/` y Paridad usaban
`expr_anio_app()`. Dos significados de «2025» en el mismo producto.

Y como sin año no se aplica predicado alguno, la agregación «All» veía filas que
ninguna agregación por año veía. Medido en producción el 14-ago-2026: **43 jobs
no cancelados** salían en «All» y en ningún año — 41 asignados en nov/dic de 2022
pero viviendo en la app de 2023, y 2 con las dos fechas NULL (`PTL3026`,
`PTL4027`). Ese es el invariante que se rompía y que aquí se fija:

    ALL == Σ años

Los dos primeros tests son estructurales y no dependen del dataset: miran el SQL
compilado. Los dos últimos son de comportamiento contra los jobs reales de
develop.
"""
from sqlmodel import func, select

from src.models.JobModel import Job
from src.services.metrics.aux_func_metrics import _year_expr
from src.services.metrics.metrics_shared import _apply_year_filter

ANIOS = (2023, 2024, 2025, 2026)

# Las columnas de las que el año NO puede depender. Ver el docstring de
# src/utils/job_app_year.py: el 100 % de los PTL tienen `Date_assigned` NULL, y
# donde las fechas existen discrepan del año de la app en 88 jobs.
COLUMNAS_DE_FECHA = ("Date_assigned", "Estimated_start_date")


def _sql(expresion) -> str:
    return str(expresion.compile(compile_kwargs={"literal_binds": True}))


def test_el_filtro_no_toca_ninguna_columna_de_fecha():
    for tipo in ("ALL", "QID", "PTL", "PAR"):
        sql = _sql(_apply_year_filter(select(Job.ID_Jobs), tipo, 2025))
        for columna in COLUMNAS_DE_FECHA:
            assert columna not in sql, (
                f"type={tipo}: el filtro de año volvió a usar {columna}. "
                "El año es la app de Podio en la que vive el ítem, no una fecha."
            )
        assert "podio_app_year" in sql, f"type={tipo}: no usa el año de app"


def test_las_dos_copias_del_predicado_no_se_bifurcan():
    """`_apply_year_filter` (WHERE) y `_year_expr` (CASE) tienen que coincidir.

    Eran dos implementaciones separadas de la misma regla, cada una con su copia
    del OR por tipo. Arreglar una y no la otra deja el dashboard de Jobs y los de
    Members/Clients/ParentCos contando cosas distintas sin que nada falle.
    """
    for tipo in ("ALL", "QID", "PTL", "PAR"):
        del_where = _sql(_apply_year_filter(select(Job.ID_Jobs), tipo, 2025))
        del_case = _sql(_year_expr(tipo, 2025))
        assert del_case in del_where, (
            f"type={tipo}: el predicado del CASE no es el mismo que el del WHERE\n"
            f"  WHERE: {del_where}\n  CASE:  {del_case}"
        )


def test_all_es_la_suma_de_los_anios(db_session):
    """El invariante que se rompía: ningún job puede quedarse sin año.

    Contra el código anterior esto falla con cualquier job de fecha NULL — y todos
    los PTL lo son.
    """
    total = db_session.exec(
        select(func.count()).select_from(Job).where(expr_anio_en_rango())
    ).one()

    por_anio = {
        anio: db_session.exec(
            _apply_year_filter(select(func.count()).select_from(Job), "ALL", anio)
        ).one()
        for anio in ANIOS
    }

    assert sum(por_anio.values()) == total, (
        f"{total - sum(por_anio.values())} jobs salen en «All» y en ningún año. "
        f"Reparto: {por_anio}"
    )


def test_cada_job_cae_en_exactamente_un_anio(db_session):
    """Ni se pierden ni se duplican: los buckets son una partición.

    La regla vieja podía perder filas (fecha NULL) pero también moverlas de año
    (fecha de dic-2022 en un job de la app 2023), y una suma correcta puede
    esconder las dos cosas cancelándose.
    """
    for anio in ANIOS:
        ids = set(
            db_session.exec(
                _apply_year_filter(select(Job.ID_Jobs), "ALL", anio)
            ).all()
        )
        fuera_de_sitio = {
            i for i in ids if i and str(i)[3:4].isdigit()
            and 2020 + int(str(i)[3:4]) != anio
        }
        assert not fuera_de_sitio, (
            f"el bucket {anio} contiene jobs de otro año: "
            f"{sorted(fuera_de_sitio)[:5]}"
        )


def expr_anio_en_rango():
    from src.utils.job_app_year import expr_anio_app

    return expr_anio_app().in_(ANIOS)
