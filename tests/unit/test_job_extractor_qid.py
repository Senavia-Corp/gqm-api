"""No-regresión (REG-016): el mapeo QID por slug que HOY funciona.

Si un cambio en FIELD_ALIASES_QID / get_job_field_value rompe alguno de
estos campos (materiales, BDF, rent, paid fees, fechas, colisión
project-name), estos tests fallan.
"""
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job

from tests.fixtures.podio_items import QID_EXPECTED, qid_item


def test_qid_canonical_mapping_exact():
    assert map_podio_item_to_job(qid_item()) == QID_EXPECTED


def test_qid_bldg_dept_fees_is_ordered_multi():
    mapped = map_podio_item_to_job(qid_item())
    assert mapped["Bldg_dept_fees"] == ["100.00", "150.00", "250.00"]


def test_qid_project_name_collision_app_order():
    # project-name-2 aparece antes que project-name en la app real:
    # Project_name toma el nombre, Po_wtn_wo toma el PO.
    mapped = map_podio_item_to_job(qid_item())
    assert mapped["Project_name"] == "Vista Lagos Ph 2"
    assert mapped["Po_wtn_wo"] == "PO-4581"


def test_qid_missing_fields_are_omitted_not_nulled():
    item = qid_item()
    item["fields"] = [f for f in item["fields"] if f["external_id"] != "calculation-10"]
    mapped = map_podio_item_to_job(item)
    assert "Gqm_paid_fees" not in mapped
