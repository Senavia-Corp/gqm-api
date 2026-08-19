"""No-regresión: los mappers de salida NO borran lo que la app no conoce.

Contexto (18-ago-2026). Los tres mappers escribían `[]` en cada campo que la
base no supiera rellenar, y `clean_podio_fields` conserva ese `[]` a propósito.
En Podio, `[]` **borra el campo**. Medido con `?dry_run=true` sobre un QID sin
costes: 18 campos salían como lista vacía — los 13 huecos `materials-purchased-*`,
los 3 `bldg-*`, `bldg-dept` y `relationship` (el cliente).

Exposición en producción: 6.497 QID (los 16 de dinero), 6.438 (`bldg-dept`) y
634 jobs de los tres tipos (`relationship`), contra una base que sólo tenía
1 alquiler aprobado, 2 BD fees y 11 compras para 7.591 jobs.

Regla: un hueco que la app no puede rellenar **no aparece en el payload**. El
borrado es explícito y pasa por `limpiar_slots`.
"""
import re

import pytest

from src.models.JobModel import Job
from src.utils.mappers.to_podio.par_mapper import map_job_to_podio_par
from src.utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from src.utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid

# Los 16 huecos de dinero de QID que se repartían por posición.
HUECOS_DINERO = re.compile(r"^(materials-purchased-|material-purchase-|bldg-fees-|bldg-dept-fees-)")


class _SesionVacia:
    """Una sesión que no encuentra nada: es la forma real de producción, donde
    la base no tiene ni costes ni compras para casi ningún job."""

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


# ---------------------------------------------------------------- QID

def test_qid_sin_costes_no_manda_ningun_hueco_de_dinero(sesion):
    payload = map_job_to_podio_qid(_qid(Job_status="Invoiced"), session=sesion, year=2026)

    huecos = [k for k in payload if HUECOS_DINERO.match(k)]
    assert huecos == [], f"el payload borraría estos huecos en Podio: {huecos}"


def test_qid_sin_cliente_no_desvincula_el_cliente(sesion):
    payload = map_job_to_podio_qid(_qid(ID_Client=None), session=sesion, year=2026)

    assert "relationship" not in payload
    assert "bldg-dept" not in payload


def test_qid_no_manda_ninguna_lista_vacia_sin_pedirlo(sesion):
    payload = map_job_to_podio_qid(_qid(Job_status="Hold"), session=sesion, year=2026)

    vacios = sorted(k for k, v in payload.items() if v == [])
    assert vacios == [], f"`[]` en Podio borra el campo; salían: {vacios}"


def test_qid_limpiar_slots_es_el_unico_canal_de_borrado(sesion):
    payload = map_job_to_podio_qid(
        _qid(), session=sesion, year=2026,
        limpiar_slots=["bldg-fees-2", "relationship"])

    assert payload["bldg-fees-2"] == []
    assert payload["relationship"] == []
    # y no arrastra a los vecinos
    assert "bldg-fees-1" not in payload
    assert "bldg-dept-fees-3" not in payload


def test_qid_los_valores_reales_siguen_saliendo(sesion):
    payload = map_job_to_podio_qid(
        _qid(Job_status="Invoiced", Project_name="Casa 4"), session=sesion, year=2026)

    assert payload["project-name-2"] == {"value": "Casa 4"}
    assert payload["job-status"] == [{"value": "Invoiced"}]


def test_qid_sin_sesion_los_huecos_salen_de_la_columna_y_sin_desplazar():
    """Sin sesión no hay registros que consultar, así que el respaldo es la
    columna del job — pero cada valor va a SU posición: un hueco intermedio
    vacío no corre a los siguientes, y tampoco se manda como borrado."""
    payload = map_job_to_podio_qid(
        _qid(Bldg_dept_fees=[120.0, None, 360.0]), session=None, year=2026)

    assert payload["bldg-fees-1"] == {"value": "120", "currency": "USD"}
    assert payload["bldg-dept-fees-3"] == {"value": "360", "currency": "USD"}
    assert "bldg-fees-2" not in payload


# ---------------------------------------------------------------- PTL y PAR

@pytest.mark.parametrize("mapper, tipo", [
    (map_job_to_podio_ptl, "PTL"),
    (map_job_to_podio_par, "PAR"),
])
def test_ptl_y_par_sin_cliente_no_lo_desvinculan(mapper, tipo, sesion):
    payload = mapper(Job(ID_Jobs=f"{tipo}-TEST", Job_type=tipo, ID_Client=None),
                     session=sesion, year=2026)

    assert "relationship" not in payload
    assert [k for k, v in payload.items() if v == []] == []


@pytest.mark.parametrize("mapper, tipo", [
    (map_job_to_podio_ptl, "PTL"),
    (map_job_to_podio_par, "PAR"),
])
def test_ptl_y_par_respetan_limpiar_slots(mapper, tipo, sesion):
    payload = mapper(Job(ID_Jobs=f"{tipo}-TEST", Job_type=tipo),
                     session=sesion, year=2026, limpiar_slots=["relationship"])

    assert payload["relationship"] == []
