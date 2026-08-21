"""Sincronizar dos veces la misma factura no puede duplicar sus lineas.

DEFECTO QUE CUBRE: `upsert_financial_doc_items` se llamaba "upsert" y solo
hacia insert — ni un SELECT previo. Cada pasada del sync masivo creaba filas
nuevas.

Los dos llamadores se comportaban distinto, y por eso no era evidente:
  · webhook/functions.py:166 y :235 BORRAN las lineas del documento antes de
    reinsertar → idempotente, nunca duplico.
  · sync_invoices_with_payments.py:136 recorre las lineas SIN borrar antes →
    duplicaba una vez por pasada.

Medido en PRODUCCION el 21-ago-2026:
    463 pares duplicados · 233 documentos · 485 filas sobrantes · $298.479,99

Y no eran solo dobles: FD60023 tenia su linea 1 TRIPLICADA.

Contra el codigo anterior, el primer test FALLA con 2 filas donde debe haber 1.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.FinancialDocItemModel import FinancialDoc_Item
from src.models.FinancialDocModel import FinancialDocument
from src.quickbooks.sync.sync_functions import upsert_financial_doc_items


@pytest.fixture()
def documento():
    sfx = uuid.uuid4().int % 90000 + 10000
    doc_id = f"FDZZ{sfx}"
    with get_session() as s:
        s.add(FinancialDocument(ID_FinancialDoc=doc_id,
                                Type_of_document="Invoice"))
        s.commit()
    yield doc_id
    with get_session() as s:
        for fila in s.exec(select(FinancialDoc_Item).where(
                FinancialDoc_Item.ID_FinancialDoc == doc_id)).all():
            s.delete(fila)
        doc = s.exec(select(FinancialDocument).where(
            FinancialDocument.ID_FinancialDoc == doc_id)).first()
        if doc:
            s.delete(doc)
        s.commit()


def _lineas(doc_id):
    with get_session() as s:
        return s.exec(select(FinancialDoc_Item).where(
            FinancialDoc_Item.ID_FinancialDoc == doc_id)).all()


def test_sincronizar_dos_veces_no_duplica(documento):
    """La misma linea de QuickBooks, dos pasadas, UNA fila."""
    linea = {"Name": "Roof repair", "Description": "labor",
             "Unit_price": 100.0, "Quantity": 2.0, "Amount": 200.0,
             "qbo_line_id": "1"}

    for _ in range(2):
        with get_session() as s:
            upsert_financial_doc_items(session=s, data=dict(linea),
                                       doc_id=documento)
            s.commit()

    filas = _lineas(documento)
    assert len(filas) == 1, (
        f"dos pasadas dejaron {len(filas)} filas. En produccion esto genero "
        f"485 filas sobrantes por $298.479,99, y algunas lineas TRIPLICADAS.")


def test_la_segunda_pasada_ACTUALIZA_el_importe(documento):
    """Si el importe cambia en QuickBooks, la fila debe reflejarlo."""
    base = {"Name": "Roof repair", "Description": "labor",
            "Unit_price": 100.0, "Quantity": 2.0, "Amount": 200.0,
            "qbo_line_id": "7"}

    with get_session() as s:
        upsert_financial_doc_items(session=s, data=dict(base), doc_id=documento)
        s.commit()

    cambiada = dict(base, Amount=350.0, Quantity=3.5)
    with get_session() as s:
        upsert_financial_doc_items(session=s, data=cambiada, doc_id=documento)
        s.commit()

    filas = _lineas(documento)
    assert len(filas) == 1, f"deberia seguir habiendo 1 fila, hay {len(filas)}"
    assert float(filas[0].Amount) == 350.0, (
        f"el importe no se actualizo: {filas[0].Amount}. Un upsert que no "
        f"actualiza deja el dato viejo en pantalla.")


def test_lineas_distintas_del_mismo_documento_conviven(documento):
    """Acotar por (documento, linea) no puede colapsar lineas legitimas."""
    for n in ("1", "2", "3"):
        with get_session() as s:
            upsert_financial_doc_items(
                session=s,
                data={"Name": f"Item {n}", "Amount": 100.0 * int(n),
                      "qbo_line_id": n},
                doc_id=documento)
            s.commit()

    filas = _lineas(documento)
    assert len(filas) == 3, (
        f"tres lineas distintas deben dar 3 filas, dieron {len(filas)}")
