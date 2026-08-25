"""No-regresión (REG-016): el mapeo QID por slug que HOY funciona.

Si un cambio en FIELD_ALIASES_QID / get_job_field_value rompe alguno de
estos campos (materiales, BDF, rent, paid fees, fechas, colisión
project-name), estos tests fallan.
"""
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job

from tests.fixtures.podio_items import QID_EXPECTED, qid_item


def test_qid_canonical_mapping_exact():
    assert map_podio_item_to_job(qid_item()) == QID_EXPECTED


def test_qid_bldg_dept_fees_ya_no_entra_por_el_mapa_generico():
    """RETIRADO 18-ago-2026 — decision, no regresion.

    El lector `multi` solo acumula los campos que VIENEN en el payload, y Podio
    no manda los vacios: con `bldg-fees-2` vacio producia `[100, 250]`, de
    longitud 2, y el importe del hueco 3 acababa escrito en la fila del hueco 2.

    Ahora los BD fees entran por `sync_bdf_from_podio`, que lee del item crudo
    por `external_id` y aplica cada importe sobre el registro que DECLARA ese
    hueco (`EstimateCost.podio_field`). La columna del job pasa a ser derivada:
    su unico escritor es `recalculate_and_apply`.
    """
    mapped = map_podio_item_to_job(qid_item())
    assert "Bldg_dept_fees" not in mapped


def test_qid_un_hueco_vacio_en_medio_no_desplaza_a_los_siguientes():
    """El desplazamiento que motivo el cambio, fijado como no-regresion."""
    from src.podio.webhook.jobs_hook_sync import _valor_money_del_item

    item = qid_item()
    for f in item["fields"]:
        if f["external_id"] == "bldg-fees-2":
            f["values"] = []

    assert _valor_money_del_item(item, "bldg-fees-1") == (True, 100.0)
    assert _valor_money_del_item(item, "bldg-fees-2") == (True, None)   # vacio, no ausente
    assert _valor_money_del_item(item, "bldg-dept-fees-3") == (True, 250.0)


def test_qid_project_name_collision_app_order():
    # project-name-2 aparece antes que project-name en la app real:
    # Project_name toma el nombre, Po_wtn_wo toma el PO.
    mapped = map_podio_item_to_job(qid_item())
    assert mapped["Project_name"] == "Vista Lagos Ph 2"
    assert mapped["Po_wtn_wo"] == "PO-4581"


def test_qid_project_name_collision_is_order_independent():
    # REG-072: aunque la app entregue project-name ANTES que project-name-2,
    # Project_name debe preferir el alias declarado primero (project-name-2).
    item = qid_item()
    item["fields"].sort(key=lambda f: f["external_id"] == "project-name-2")
    mapped = map_podio_item_to_job(item)
    assert mapped["Project_name"] == "Vista Lagos Ph 2"
    assert mapped["Po_wtn_wo"] == "PO-4581"


def test_qid_2023_style_only_project_name():
    # App 2023: solo existe project-name (es el nombre del proyecto).
    item = qid_item()
    item["fields"] = [f for f in item["fields"] if f["external_id"] != "project-name-2"]
    mapped = map_podio_item_to_job(item)
    assert mapped["Project_name"] == "PO-4581"


def test_qid_missing_fields_are_omitted_not_nulled():
    item = qid_item()
    item["fields"] = [f for f in item["fields"] if f["external_id"] != "calculation-10"]
    mapped = map_podio_item_to_job(item)
    assert "Gqm_paid_fees" not in mapped
