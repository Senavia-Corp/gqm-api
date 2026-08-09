"""No-regresión (REG-016) PTL/PAR + decisión de pagos parciales.

Decisión confirmada (DECISIONES-CONFIRMADAS.md): PTL NO usa pagos
parciales — payment-received-1/2/3 y payment-date-and-check-* se ignoran
a propósito. PAR sí los usará (REG-001, se modela en este bloque).
"""
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job

from tests.fixtures.podio_items import PAR_EXPECTED, PTL_EXPECTED, par_item, ptl_item


def test_ptl_canonical_mapping_exact():
    assert map_podio_item_to_job(ptl_item()) == PTL_EXPECTED


def test_ptl_payment_fields_are_ignored_by_decision():
    mapped = map_podio_item_to_job(ptl_item(with_payments=True))
    assert not [k for k in mapped if "payment" in k.lower()]
    # y su presencia no altera el resto del mapeo
    assert mapped == PTL_EXPECTED


def test_ptl_gc_fee_maps_from_money_2():
    assert map_podio_item_to_job(ptl_item())["Ptl_gc_fee"] == "800.00"


def test_par_canonical_mapping_exact():
    assert map_podio_item_to_job(par_item()) == PAR_EXPECTED
