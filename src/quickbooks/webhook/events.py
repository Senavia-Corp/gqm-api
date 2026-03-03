from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.models.FinancialDocModel import FinancialDocument
from src.models.FinancialTransModel import FinancialTransaction
from src.utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from src.utils.middleware.retries.db_route_retries.add_session import save_with_retry
from src.quickbooks.webhook.functions import recalculate_document_from_db


# -------- Evento Voided
def event_void_qbo(session, Model, qbo_id):
    existing = session.exec(
        select(Model).where(Model.qbo_id == qbo_id)
    ).first()

    if existing and not existing.is_voided:
        existing.is_voided = True
        existing.Total_Amount = 0

        # Si es un documento (Invoice/Bill), limpiamos balances
        if hasattr(existing, "Balance_Amount"):
            existing.Balance_Amount = 0
            existing.Percentage_Paid = 0

        session.add(existing)
        session.flush()

        if isinstance(existing, FinancialTransaction):
            for doc in existing.financial_documents:
                recalculate_document_from_db(session, doc.qbo_id)

        session.commit()
        print(f"🚫 Registro {qbo_id} marcado como VOID y balances actualizados")


# -------- Evento Emailed
def event_email_qbo(session, Model, qbo_id):
    existing = session.exec(
        select(Model).where(Model.qbo_id == qbo_id)
    ).first()

    if existing and not existing.is_emailed:
        existing.is_emailed = True
        save_with_retry(session, existing)


# -------- Evento Delete
def event_delete_qbo(realm_id: str, entity_type: str, qbo_id: str):
    with get_session() as session:
        # --- CASO FACTURAS/BILLS ---
        if entity_type in ("Invoice", "Bill"):
            doc = session.exec(select(FinancialDocument).where(
                FinancialDocument.qbo_id == qbo_id)).first()
            if doc:
                delete_with_retry(session, doc)
                print(f"🗑️ {entity_type} {qbo_id} eliminado")

        # --- CASO PAGOS (Requiere lógica extra) ---
        elif entity_type in ("Payment", "BillPayment"):
            trans = session.exec(select(FinancialTransaction).where(
                FinancialTransaction.qbo_id == qbo_id)).first()
            if trans:
                # 1. Extraemos los QBO_IDs de las facturas ANTES de borrar
                affected_doc_ids = [
                    doc.qbo_id for doc in trans.financial_documents]

                # 2. Borramos el pago (hace commit interno)
                delete_with_retry(session, trans)

                # 3. Recalculamos las facturas afectadas una por una
                for d_id in affected_doc_ids:
                    recalculate_document_from_db(session, d_id)
                    session.commit()  # Guardamos el nuevo balance de la factura

                print(
                    f"🗑️ Pago {qbo_id} eliminado y {len(affected_doc_ids)} facturas actualizadas")
