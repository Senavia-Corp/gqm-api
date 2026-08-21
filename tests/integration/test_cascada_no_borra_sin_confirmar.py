"""Si Podio no confirma el borrado, NO se puede tocar la cascada del job.

DEFECTO QUE CUBRE (encontrado por la verificacion adversarial del 21-ago-2026):
`ecaabfb` anadio la confirmacion contra Podio para que un POST sin autenticar no
pudiera borrar jobs. Pero la puso DENTRO de `event_delete`, que en la cascada se
llama AL FINAL — despues de haber borrado ya change orders, documentos
financieros, orders y links.

Asi que cuando Podio respondia "sigue vivo" o "no puedo confirmar":
  · el Job sobrevivia  ✅ (que era el objetivo del arreglo)
  · y TODOS sus hijos quedaban borrados y commiteados  ❌

Un job vivo sin sus orders, sin sus change orders y sin sus documentos
financieros. Silencioso, ademas: `sentinela_huerfanos` cuenta filas sin job, no
jobs sin filas.

En produccion cuelgan 9.711 orders, 1.281 change orders y 2.979 documentos
financieros de 7.620 jobs.

Estos tests fallan contra el codigo anterior al arreglo.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.ChangeOrderModel import ChangeOrder
from src.models.FinancialDocModel import FinancialDocument
from src.models.JobModel import Job
from src.models.OrderModel import Order


@pytest.fixture()
def job_con_hijos():
    sfx = uuid.uuid4().int % 90000 + 10000
    item_id = str(920000000 + sfx)
    ids = {
        "item_id": item_id,
        "job": f"QID9{sfx}",
        "order": f"ORDZ{sfx}",
        "co": f"CHOZ{sfx}",
        "fdoc": f"FDZ{sfx}",
    }
    with get_session() as s:
        s.add(Job(ID_Jobs=ids["job"], Job_type="QID", podio_item_id=item_id))
        s.add(Order(ID_Order=ids["order"], job_podio_id=item_id, Formula=100.0))
        s.add(ChangeOrder(ID_ChangeOrder=ids["co"], job_podio_id=item_id,
                          ID_Order=ids["order"]))
        s.add(FinancialDocument(ID_FinancialDoc=ids["fdoc"], ID_Jobs=ids["job"],
                                Type_of_document="Bill"))
        s.commit()
    yield ids
    with get_session() as s:
        for modelo, campo, val in (
                (FinancialDocument, "ID_FinancialDoc", ids["fdoc"]),
                (ChangeOrder, "ID_ChangeOrder", ids["co"]),
                (Order, "ID_Order", ids["order"]),
                (Job, "ID_Jobs", ids["job"])):
            fila = s.exec(select(modelo).where(
                getattr(modelo, campo) == val)).first()
            if fila:
                s.delete(fila)
        s.commit()


def _hijos_vivos(ids):
    with get_session() as s:
        return {
            "job": s.exec(select(Job).where(Job.ID_Jobs == ids["job"])).first() is not None,
            "order": s.exec(select(Order).where(Order.ID_Order == ids["order"])).first() is not None,
            "co": s.exec(select(ChangeOrder).where(ChangeOrder.ID_ChangeOrder == ids["co"])).first() is not None,
            "fdoc": s.exec(select(FinancialDocument).where(FinancialDocument.ID_FinancialDoc == ids["fdoc"])).first() is not None,
        }


@pytest.mark.parametrize("respuesta_podio, motivo", [
    (True, "el item SIGUE VIVO en Podio"),
    (None, "no se pudo CONFIRMAR contra Podio (5xx / red)"),
])
def test_si_podio_no_confirma_no_se_borra_ni_un_hijo(
        monkeypatch, job_con_hijos, respuesta_podio, motivo):
    from src.routes import Webhook_bp as wb
    from src.utils import podio_webhook_core as pwc

    # Se parchea el MODULO DE ORIGEN, que comparten el camino nuevo y el viejo
    # (`event_delete`). Asi este test ejercita la perdida de datos real contra
    # el codigo anterior, en vez de morir con un AttributeError.
    monkeypatch.setattr(pwc, "item_sigue_vivo_en_podio",
                        lambda *a, **k: respuesta_podio)

    with get_session() as s:
        wb._cascade_delete_job_from_podio(
            s, job_con_hijos["item_id"], app_type="QID", year=2026)
        s.commit()

    vivos = _hijos_vivos(job_con_hijos)
    assert vivos == {"job": True, "order": True, "co": True, "fdoc": True}, (
        f"con «{motivo}» no se puede borrar NADA, y quedo: {vivos}. "
        f"Antes del arreglo el job sobrevivia pero sus hijos no."
    )


def test_si_podio_confirma_el_borrado_la_cascada_si_corre(
        monkeypatch, job_con_hijos):
    """Control positivo: el arreglo no puede impedir los borrados legitimos."""
    from src.routes import Webhook_bp as wb
    from src.utils import podio_webhook_core as pwc

    monkeypatch.setattr(pwc, "item_sigue_vivo_en_podio", lambda *a, **k: False)

    with get_session() as s:
        wb._cascade_delete_job_from_podio(
            s, job_con_hijos["item_id"], app_type="QID", year=2026)
        s.commit()

    vivos = _hijos_vivos(job_con_hijos)
    assert vivos == {"job": False, "order": False, "co": False, "fdoc": False}, (
        f"con Podio confirmando que el item ya no existe, la cascada DEBE "
        f"correr entera. Quedo: {vivos}")
