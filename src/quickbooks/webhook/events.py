from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.models.FinancialDocModel import FinancialDocument
from src.models.FinancialTransModel import FinancialTransaction
from src.utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# -------- Evento Voided
def event_void_qbo(session, Model, qbo_id):
    existing = session.exec(
        select(Model).where(Model.qbo_id == qbo_id)
    ).first()

    if existing and not existing.is_voided:
        existing.is_voided = True
        existing.Total_Amount = 0
        existing.Balance_Amount = 0
        existing.Percentage_Paid = 0

        session.add(existing)
        session.commit()

        print(f"🚫 Registro {qbo_id} marcado como VOID en la DB")


# -------- Evento Emailed
def event_email_qbo(session, Model, qbo_id):
    existing = session.exec(
        select(Model).where(Model.qbo_id == qbo_id)
    ).first()

    if existing and not existing.is_emailed:
        existing.is_emailed = True
        session.add(existing)
        session.commit()


# -------- Evento Delete
def event_delete_qbo(realm_id: str, entity_type: str, qbo_id: str):

    with get_session() as session:

        if entity_type in ("Invoice", "Bill"):
            doc = session.exec(
                select(FinancialDocument).where(
                    FinancialDocument.qbo_id == qbo_id)).first()

            if doc:
                delete_with_retry(session, doc)
                print(f"🗑️ {entity_type} {qbo_id} eliminado")
            else:
                print(f"⚠️ {entity_type} {qbo_id} no existe localmente")

        elif entity_type in ("Payment", "BillPayment"):

            trans = session.exec(
                select(FinancialTransaction).where(
                    FinancialTransaction.qbo_id == qbo_id)).first()

            if trans:
                delete_with_retry(session, trans)
                print(f"🗑️ {entity_type} {qbo_id} eliminado")
            else:
                print(f"⚠️ {entity_type} {qbo_id} no existe localmente")

        else:
            print(f"⚠️ Tipo no soportado en delete: {entity_type}")
