"""No-regresión: el 0 de un agregado NO se manda a Podio.

Contexto (2-sep-2026). Hermano exacto de `test_mappers_no_borran_huecos.py`:
allí la ausencia de dato llegaba como `None` y se escribía `[]`; aquí llega
como **0** y se escribía el importe 0, que en un campo `money` de Podio pisa
el valor real.

Los tres totales de QID (`estimated-material-total`, `estimated-hoa-admin-total`,
`fees-and-cost`) y los dos de PTL los reconstruye
`job_calculator.recalculate_job_fields` desde los `EstimateCost`, así que un job
cuyas líneas nunca cruzaron la API los tiene a 0.

Medido con `PATCH /jobs/QID6904?dry_run=true`: el payload llevaba
`estimated-material-total = 0` mientras Podio tenía **437,91**. En la app QID
2026, 227 ítems tienen material distinto de 0 en Podio y **165 tienen 0/NULL en
la BD**: una sola edición del panel se los ponía a 0.
"""
import pytest

from src.models.JobModel import Job
from src.utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from src.utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid

TOTALES_QID = ("estimated-material-total", "estimated-hoa-admin-total", "fees-and-cost")


class _SesionVacia:
    """La forma real de producción: la base no tiene costes para casi ningún job."""

    def exec(self, _statement):
        return self

    def first(self):
        return None

    def all(self):
        return []


@pytest.fixture
def sesion():
    return _SesionVacia()


def _qid(**kw):
    return Job(ID_Jobs="QID-TEST", Job_type="QID", **kw)


def test_qid_sin_lineas_no_pisa_los_tres_totales(sesion):
    payload = map_job_to_podio_qid(
        _qid(Estimated_material=0.0, Estimated_rent=0.0, Estimated_city=0.0),
        session=sesion, year=2026)

    presentes = [k for k in TOTALES_QID if k in payload]
    assert presentes == [], f"estos borrarían el importe real en Podio: {presentes}"


def test_qid_el_total_de_verdad_sigue_saliendo(sesion):
    payload = map_job_to_podio_qid(
        _qid(Estimated_material=437.91), session=sesion, year=2026)

    assert float(payload["estimated-material-total"]["value"]) == 437.91


def test_qid_un_importe_no_calculado_sale_aunque_valga_cero(sesion):
    """La guarda mira `CAMPOS_CALCULADOS_EN_LOCAL`, no «money que vale 0».

    `Gqm_target_sold_pricing` es un dato tecleado, no un agregado: ponerlo a 0
    es una decisión, y tiene que llegar a Podio.
    """
    payload = map_job_to_podio_qid(
        _qid(Gqm_target_sold_pricing=0.0), session=sesion, year=2026)

    assert float(payload["gqm-target-sold-price"]["value"]) == 0


def test_qid_limpiar_slots_sigue_siendo_el_canal_de_borrado(sesion):
    payload = map_job_to_podio_qid(
        _qid(Estimated_material=0.0), session=sesion, year=2026,
        limpiar_slots=["estimated-material-total"])

    assert payload["estimated-material-total"] == []


def test_ptl_sin_lineas_no_pisa_sus_dos_agregados(sesion):
    payload = map_job_to_podio_ptl(
        Job(ID_Jobs="PTL-TEST", Job_type="PTL",
            Estimated_material=0.0, Ptl_gc_fee=0.0),
        session=sesion, year=2026)

    assert "fees-and-cost" not in payload   # Estimated_material en PTL
    assert "money-2" not in payload         # Ptl_gc_fee
