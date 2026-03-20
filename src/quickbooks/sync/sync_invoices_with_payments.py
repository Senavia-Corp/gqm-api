from datetime import date
from src.database.db_sqlmodel import get_session
from src.utils.mappers.qbo_aux_functions import attach_job_code
from ..services.invoices_services import get_invoices_by_job
from src.quickbooks.services.qbo_base_services import qbo_query
from .sync_functions import (
    upsert_financial_document,
    upsert_financial_doc_items,
    upsert_financial_transaction,
    upsert_financial_link
)
from src.utils.mappers.from_qbo.field_maps import (
    QBO_FDOC_FIELD_MAP,
    QBO_FDOCITEM_INVOICE_FIELD_MAP,
    QBO_FTRANS_INVOICE_FIELD_MAP
)
from src.utils.mappers.qbo_aux_functions import calculate_percentage_paid
from src.utils.mappers.from_qbo.mapper import map_entity
from src.models.FinancialDocModel import DocumentType
from src.models.FinancialTransModel import TransactionType


def _get_amount_applied_from_payment(payment_data: dict, invoice_qbo_id: str) -> float | None:

    # Extrae el monto aplicado a una Invoice específica dentro de las líneas del Payment.
    for line in payment_data.get("Line", []):
        linked_txns = line.get("LinkedTxn", [])
        for linked in linked_txns:
            if (
                linked.get("TxnType") == "Invoice"
                and linked.get("TxnId") == invoice_qbo_id
            ):
                amount = line.get("Amount")
                return float(amount) if amount is not None else None
    return None


def _get_date_applied_from_payment(payment_data: dict) -> date | None:
    """Extrae la fecha del pago (TxnDate) como objeto date."""
    txn_date = payment_data.get("TxnDate")
    if not txn_date:
        return None
    try:
        return date.fromisoformat(txn_date)
    except (ValueError, TypeError):
        return None


def sync_qbo_invoices_and_payments_by_job(
    realm_id: str,
    job_code: str,
    start: int = 1,
    limit: int = 100,
    dry_run: bool = False
):
    # -----------------------------------
    # 1️⃣ OBTENER INVOICES POR JOB
    # -----------------------------------
    response = get_invoices_by_job(
        realm_id=realm_id,
        job_code=job_code,
        start=start,
        limit=limit
    )

    invoices = response.get("QueryResponse", {}).get("Invoice", [])

    if not invoices:
        return {"processed": 0, "job_code": job_code}

    # -----------------------------------
    # 2️⃣ EXTRAER PAYMENT IDS LIGADOS
    # -----------------------------------
    payment_ids = set()

    for inv in invoices:
        for txn in inv.get("LinkedTxn", []):
            if txn.get("TxnType") == "Payment":
                payment_ids.add(txn.get("TxnId"))

    # -----------------------------------
    # 3️⃣ TRAER PAYMENTS EN BLOQUE
    # -----------------------------------
    payments_info = {}

    if payment_ids:
        ids_string = ",".join(f"'{p_id}'" for p_id in payment_ids)
        query = f"SELECT * FROM Payment WHERE Id IN ({ids_string})"
        payments_data = qbo_query(realm_id, query)

        for p in payments_data.get("QueryResponse", {}).get("Payment", []):
            payments_info[p["Id"]] = p

    # -----------------------------------
    # 4️⃣ PROCESAR Y GUARDAR
    # -----------------------------------
    with get_session() as session:

        processed_count = 0

        for invoice in invoices:

            # -----------------------------
            # 1️⃣ MAPEAR DOCUMENTO
            # -----------------------------
            mapped_doc = map_entity(invoice, QBO_FDOC_FIELD_MAP)
            mapped_doc = attach_job_code(mapped_doc)

            # -----------------------------
            # 2️⃣ CALCULAR PERCENTAGE PAID
            # -----------------------------
            mapped_doc["Percentage_Paid"] = calculate_percentage_paid(
                mapped_doc.get("Total_Amount"),
                mapped_doc.get("Balance_Amount")
            )

            # -----------------------------
            # 3️⃣ UPSERT FINANCIAL DOCUMENT
            # -----------------------------
            doc_obj, _ = upsert_financial_document(
                session=session,
                data=mapped_doc,
                doc_type=DocumentType.Invoice,
                dry_run=dry_run
            )

            if not doc_obj:
                continue

            # Guardamos el qbo_id de la invoice para cruzar con las líneas del pago
            invoice_qbo_id = invoice.get("Id")

            # -----------------------------
            # 4️⃣ UPSERT ITEMS
            # -----------------------------
            for line in invoice.get("Line", []):
                if line.get("DetailType") != "SalesItemLineDetail":
                    continue
                mapped_item = map_entity(line, QBO_FDOCITEM_INVOICE_FIELD_MAP)
                upsert_financial_doc_items(
                    session=session,
                    data=mapped_item,
                    doc_id=doc_obj.ID_FinancialDoc,
                    dry_run=dry_run
                )

            # -----------------------------
            # 5️⃣ UPSERT PAYMENTS LIGADOS
            # -----------------------------
            for txn in invoice.get("LinkedTxn", []):

                if txn.get("TxnType") != "Payment":
                    continue

                payment_id = txn.get("TxnId")

                if payment_id not in payments_info:
                    continue

                payment_data = payments_info[payment_id]

                mapped_trans = map_entity(
                    payment_data, QBO_FTRANS_INVOICE_FIELD_MAP)

                trans_obj, _ = upsert_financial_transaction(
                    session=session,
                    data=mapped_trans,
                    trans_type=TransactionType.Invoice_payments,
                    dry_run=dry_run
                )

                if trans_obj:
                    # Extraer cuánto de este pago se aplicó a esta Invoice específica
                    amount_applied = _get_amount_applied_from_payment(
                        payment_data, invoice_qbo_id
                    )
                    date_applied = _get_date_applied_from_payment(payment_data)

                    upsert_financial_link(
                        session=session,
                        doc_id=doc_obj.ID_FinancialDoc,
                        trans_id=trans_obj.ID_FTransaction,
                        amount_applied=amount_applied,
                        date_applied=date_applied,
                        dry_run=dry_run
                    )

            processed_count += 1

        if not dry_run:
            session.commit()

    return {
        "processed": processed_count,
        "job_code": job_code,
        "limit": limit,
        "start": start,
        "dry_run": dry_run
    }
