"""REG-076: el writer (to_podio) y el lector (from_podio) deben cubrir los
mismos slots de técnico con los mismos slugs."""
from src.utils.mappers.from_podio.order_changeorder_mapper import (
    ORDER_CHANGE_ORDERS_FIELDS,
    TECH_FORMULA_FIELDS,
    TECHNICIAN_FIELDS,
)
from src.utils.mappers.to_podio.order_changeorder_fields_map import (
    ORDER_CO_QID_FIELDS,
    ORDER_QID_FIELDS,
)


def test_qid_writer_covers_all_reader_slots():
    reader_slots = set(TECH_FORMULA_FIELDS["QID"])
    writer_slots = set(ORDER_QID_FIELDS["Formula"])
    assert writer_slots == reader_slots  # 1..20


def test_qid_co_writer_covers_all_reader_slots():
    # El writer de Change Orders por técnico también debe llegar a 20 y sus
    # slugs deben existir en el lector (hallazgo del code-reviewer B1).
    reader = ORDER_CHANGE_ORDERS_FIELDS["QID"]
    assert set(ORDER_CO_QID_FIELDS) == set(reader)
    for slot, slugs in ORDER_CO_QID_FIELDS.items():
        for slug in slugs:
            assert slug in reader[slot], f"slot {slot}: '{slug}' no está en el lector"


def test_qid_writer_slugs_match_reader():
    for slot, slug in ORDER_QID_FIELDS["Formula"].items():
        assert slug in TECH_FORMULA_FIELDS["QID"][slot], (
            f"slot {slot}: writer '{slug}' no está en el lector")
    for slot, slug in ORDER_QID_FIELDS["ID_Subcontractor"].items():
        assert slug in TECHNICIAN_FIELDS[slot], (
            f"slot {slot}: technician writer '{slug}' no está en el lector")
