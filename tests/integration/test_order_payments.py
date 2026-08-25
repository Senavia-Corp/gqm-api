"""Cuotas a técnico: QID y PAR, en los dos sentidos y sin tope de tres.

G7/M9 de la auditoría. El mapa sólo cubría PAR y sólo 3 cuotas, mientras Podio
tiene 11 para el técnico 1 de QID. Medido en producción: 9.066 órdenes QID con
$0,00 en pagos frente a $41,5 M en fórmulas, y los cheques sí estaban en Podio.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.OrderModel import Order
from src.models.OrderPaymentModel import OrderPayment
from src.utils.mappers.from_podio import payment_slots
from tests.fixtures.podio_items import calc, money, qid_item


def _unique():
    n = uuid.uuid4().int % 90000 + 10000
    return 900000000 + n, f"QID9{n}"


def _post(client, item, event="item.create", tipo="QID", anio=2026):
    from decouple import config
    token = config("PODIO_WEBHOOK_TOKEN", default="")
    return client.post(f"/webhook/podio/jobs/{tipo}/{anio}/{token}",
                       json={"type": event, "item_id": item["item_id"], "item": item})


@pytest.fixture()
def qid_ids():
    item_id, tracking = _unique()
    yield item_id, tracking
    with get_session() as s:
        for o in s.exec(select(Order).where(Order.job_podio_id == str(item_id))).all():
            for c in s.exec(select(OrderPayment).where(
                    OrderPayment.ID_Order == o.ID_Order)).all():
                s.delete(c)
            s.delete(o)
        j = s.exec(select(Job).where(Job.ID_Jobs == tracking)).first()
        if j:
            s.delete(j)
        s.commit()


def _cuotas(item_id):
    with get_session() as s:
        return s.exec(select(OrderPayment)
                      .where(OrderPayment.job_podio_id == str(item_id))
                      .order_by(OrderPayment.Installment)).all()


def test_qid_lee_las_once_cuotas_del_tecnico_1(client, qid_ids):
    """Antes QID no tenía modelo de pagos: `TECH_PAYMENT_FIELDS` sólo tenía PAR."""
    item_id, tracking = qid_ids
    item = qid_item(item_id=item_id, tracking_id=tracking)
    item["fields"] += [calc("tech-1-ptl-original-pricing", "5000.00")]

    mapa = payment_slots.mapa_pagos("QID", 2026)[1]
    assert len(mapa) == 11, "el técnico 1 de QID tiene 11 huecos de cuota"
    for numero, ext in mapa.items():
        item["fields"].append(money(ext, f"{numero * 100}.00"))

    assert _post(client, item).status_code == 200

    cuotas = _cuotas(item_id)
    assert [c.Installment for c in cuotas] == list(range(1, 12))
    assert [c.Amount for c in cuotas] == [n * 100.0 for n in range(1, 12)]
    assert [c.podio_field for c in cuotas] == [mapa[n] for n in range(1, 12)]


def test_las_cuotas_1_a_3_se_proyectan_en_payment_1_2_3(client, qid_ids):
    """Compatibilidad mientras el panel no lea `order_payment`."""
    item_id, tracking = qid_ids
    item = qid_item(item_id=item_id, tracking_id=tracking)
    item["fields"] += [
        calc("tech-1-ptl-original-pricing", "5000.00"),
        money("check-amount-payment-1", "111.00"),
        money("check-amount-payment-2", "222.00"),
        money("tech-1-payment-7", "777.00"),
    ]
    assert _post(client, item).status_code == 200

    with get_session() as s:
        order = s.exec(select(Order).where(Order.job_podio_id == str(item_id))).first()
        assert (order.Payment_1, order.Payment_2, order.Payment_3) == (111.0, 222.0, None)

    # y la 7 existe, aunque no quepa en las columnas viejas
    assert any(c.Installment == 7 and c.Amount == 777.0 for c in _cuotas(item_id))


def test_borrar_una_cuota_intermedia_en_podio_no_mueve_a_las_demas(client, qid_ids):
    item_id, tracking = qid_ids
    mapa = payment_slots.mapa_pagos("QID", 2026)[1]

    item = qid_item(item_id=item_id, tracking_id=tracking)
    item["fields"] += [calc("tech-1-ptl-original-pricing", "5000.00")]
    for numero in (5, 6, 7):
        item["fields"].append(money(mapa[numero], f"{numero * 10}.00"))
    assert _post(client, item).status_code == 200

    # la 6 desaparece del payload
    otro = qid_item(item_id=item_id, tracking_id=tracking)
    otro["fields"] += [calc("tech-1-ptl-original-pricing", "5000.00"),
                       money(mapa[5], "50.00"), money(mapa[7], "70.00")]
    assert _post(client, otro, event="item.update").status_code == 200

    por_numero = {c.Installment: (c.Amount, c.podio_field) for c in _cuotas(item_id)}
    assert por_numero[5] == (50.0, mapa[5])
    assert por_numero[7] == (70.0, mapa[7]), "la 7 no puede caer en el hueco de la 6"
    assert por_numero[6] == (60.0, mapa[6]), "vaciar en Podio no borra la cuota"


def test_ptl_sigue_sin_cuotas_parciales(client):
    """Decisión de cliente ya cerrada, expresada como dato en el artefacto."""
    assert payment_slots.habilitado("PTL") is False
    assert payment_slots.collect_payment_slots(
        [money("check-amount-payment-1", "100.00")], "PTL", 2026) == {}


def test_par_2023_no_tiene_tecnico_3(client):
    """Bug latente que el mapa sin año arrastraba: `tech-3-payment-*` no existe
    en PAR 2023, así que escribir ahí habría dado `field.not.found`."""
    assert sorted(payment_slots.mapa_pagos("PAR", 2023)) == [1, 2]
    assert sorted(payment_slots.mapa_pagos("PAR", 2026)) == [1, 2, 3, 4]
    assert payment_slots.slot_de_cuota("PAR", 2023, 3, 1) is None
