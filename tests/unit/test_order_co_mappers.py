"""No-regresión de la estructura del registry de Orders/COs to_podio."""
from src.utils.mappers.to_podio.order_changeorder_mappers import (
    JOB_TYPE_FIELD_REGISTRY,
    map_chorder_create_to_podio,
)


class _StubCO:
    ID_Order = None
    ID_ChangeOrder = "CO_TEST"
    job_podio_id = "0"
    ChangeOrderFormula = 100.0
    podio_field = None


def test_registry_qid_ptl_support_change_orders():
    for job_type in ("QID", "PTL"):
        assert {"order", "project_co", "order_co"} <= set(JOB_TYPE_FIELD_REGISTRY[job_type])


def test_par_registry_has_no_change_orders():
    # Decisión: PAR no soporta Change Orders (solo pagos parciales).
    assert set(JOB_TYPE_FIELD_REGISTRY["PAR"]) == {"order"}


def test_par_project_co_mapper_returns_none():
    assert map_chorder_create_to_podio(_StubCO(), "PAR", {}, session=None) is None


def test_par_order_co_mapper_returns_none():
    co = _StubCO()
    co.ID_Order = "ORD_TEST"
    assert map_chorder_create_to_podio(co, "PAR", {}, session=None) is None
