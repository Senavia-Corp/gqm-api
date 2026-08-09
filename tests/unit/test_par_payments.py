"""REG-001: cuotas de PAR — collect_payment_slots."""
from src.utils.mappers.from_podio.order_changeorder_mapper import collect_payment_slots

from tests.fixtures.podio_items import money


def test_par_payment_slots_by_tech_and_position():
    fields = [
        money("check-amount-payment-1", "300.00"),
        money("check-amount-payment-2", "200.00"),
        money("check-amount-payment-1-2", "500.00"),
        money("tech-3-payment-2", "150.00"),
    ]
    assert collect_payment_slots(fields, "PAR") == {
        1: {1: 300.00, 2: 200.00},
        2: {1: 500.00},
        3: {2: 150.00},
    }


def test_qid_and_ptl_have_no_payment_model():
    fields = [money("check-amount-payment-1", "300.00")]
    assert collect_payment_slots(fields, "QID") == {}
    assert collect_payment_slots(fields, "PTL") == {}


def test_non_numeric_values_are_skipped():
    fields = [money("check-amount-payment-1", "no-numérico")]
    assert collect_payment_slots(fields, "PAR") == {}
