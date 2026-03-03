from src.models.FinancialTransModel import TransactionType
from src.models.FinancialDocModel import FinancialDocument, DocumentType
from src.models.FinancialDocItemModel import FinancialDoc_Item
from src.utils.mappers.from_qbo.mapper import map_entity
from src.utils.mappers.qbo_aux_functions import calculate_percentage_paid
from src.utils.mappers.from_qbo.field_maps import (
    QBO_FDOC_FIELD_MAP,
    QBO_FDOCITEM_INVOICE_FIELD_MAP,
    QBO_FDOCITEM_BILL_FIELD_MAP,
    QBO_FTRANS_INVOICE_FIELD_MAP,
    QBO_FTRANS_BILL_FIELD_MAP
)
from src.quickbooks.sync.sync_functions import (
    upsert_financial_document,
    upsert_financial_doc_items,
    upsert_financial_transaction,
    upsert_financial_link
)
from src.quickbooks.services.qbo_base_services import qbo_query
from src.utils.mappers.qbo_aux_functions import attach_job_code
from src.database.db_sqlmodel import get_session
from sqlmodel import select, delete
import hmac
import hashlib
import base64
import os
import logging

logger = logging.getLogger(__name__)


# ==========================================================
# ------------- Función para validar el webhook ------------
# ==========================================================
def validate_qbo_signature(raw_body: bytes, signature: str) -> bool:
    """
    Valida la firma de un webhook de QuickBooks Online.
    """
    if not signature:
        logger.warning("❌ No signature header received")
        return False

    verifier_token = os.getenv("QBO_VERIFIER_TOKEN")
    if not verifier_token:
        logger.error("❌ QBO_VERIFIER_TOKEN is not set in environment")
        return False

    try:
        # 1. Generar el hash usando la clave secreta y el cuerpo crudo
        hashed = hmac.new(
            verifier_token.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).digest()

        # 2. Codificar a Base64 para comparar con el header de QBO
        expected_signature = base64.b64encode(hashed).decode()

        # 3. Comparación segura contra ataques de tiempo
        return hmac.compare_digest(expected_signature, signature)

    except Exception as e:
        logger.error(f"❌ Error during signature validation: {e}")
        return False


# ============================================================
# -- Función para modificar doc si hay cambio en los payments
# ============================================================
def recalculate_document_from_db(session, qbo_id):
    # Buscamos el documento por su ID de QuickBooks
    doc = session.exec(
        select(FinancialDocument).where(
            FinancialDocument.qbo_id == qbo_id
        )
    ).first()

    if not doc:
        print(f"⚠️ No se encontró el documento {qbo_id} para recalcular.")
        return

    total_paid = sum(
        trans.Total_Amount
        for trans in doc.financial_transactions
        if trans.Total_Amount is not None and not trans.is_voided
    )

    # Actualizamos los campos del documento
    doc.Balance_Amount = (doc.Total_Amount or 0) - total_paid

    # Calculamos el porcentaje pagado (asegurándote de que no divida por cero)
    doc.Percentage_Paid = calculate_percentage_paid(
        doc.Total_Amount,
        doc.Balance_Amount
    )

    session.add(doc)
    # No hace falta commit aquí si se llama dentro de una función que ya hace commit al final
    print(
        f"📊 Balance recalculado para {doc.ID_FinancialDoc}: Pagado={total_paid}, Pendiente={doc.Balance_Amount}")


# ==========================================================
# -- Función para procesar UNA sola entidad (individual) --
# ==========================================================
def process_single_entity_qbo(realm_id: str, entity_type: str, qbo_id: str, dry_run: bool = False):
    # 1. Una sola llamada a la API por ejecución
    query = f"SELECT * FROM {entity_type} WHERE Id = '{qbo_id}'"
    response = qbo_query(realm_id, query)
    entity_list = response.get("QueryResponse", {}).get(entity_type, [])

    if not entity_list:
        print(f"⚠️ {entity_type} {qbo_id} no encontrado")
        return

    entity = entity_list[0]

    with get_session() as session:
        # Usamos un diccionario de mapeo para evitar IFs gigantes
        if entity_type == "Invoice":
            _handle_invoice(session, entity, realm_id, dry_run)
        elif entity_type == "Bill":
            _handle_bill(session, entity, realm_id, dry_run)
        elif entity_type == "Payment":
            _handle_payment(session, entity, dry_run)
        elif entity_type == "BillPayment":
            _handle_bill_payment(session, entity, dry_run)

        if not dry_run:
            session.commit()

    print(f"✅ {entity_type} {qbo_id} procesado")

# --- FUNCIONES AUXILIARES PARA EVITAR RECURSIVIDAD ---


def _handle_invoice(session, entity, realm_id, dry_run):
    mapped_doc = map_entity(entity, QBO_FDOC_FIELD_MAP)
    mapped_doc = attach_job_code(mapped_doc)

    # Cálculo local rápido
    mapped_doc["Percentage_Paid"] = calculate_percentage_paid(
        mapped_doc.get("Total_Amount"), mapped_doc.get("Balance_Amount")
    )

    doc_obj, _ = upsert_financial_document(
        session=session, data=mapped_doc,
        doc_type=DocumentType.Invoice, dry_run=dry_run
    )

    if doc_obj and not dry_run:
        # Se borran todos los items actuales de ESTE documento antes de reinsertar
        session.exec(
            delete(FinancialDoc_Item).where(
                FinancialDoc_Item.ID_FinancialDoc == doc_obj.ID_FinancialDoc)
        )
        # Se buscan los items y se actualiza
        for line in entity.get("Line", []):
            if line.get("DetailType") == "SalesItemLineDetail":
                mapped_item = map_entity(line, QBO_FDOCITEM_INVOICE_FIELD_MAP)
                upsert_financial_doc_items(
                    session, mapped_item, doc_obj.ID_FinancialDoc, dry_run)


def _handle_payment(session, entity, dry_run):
    mapped_trans = map_entity(entity, QBO_FTRANS_INVOICE_FIELD_MAP)
    trans_obj, _ = upsert_financial_transaction(
        session=session, data=mapped_trans,
        trans_type=TransactionType.Invoice_payments, dry_run=dry_run
    )

    if trans_obj:
        for line in entity.get("Line", []):
            for linked in line.get("LinkedTxn", []):
                linked_id = linked.get("TxnId")
                # Solo recalculamos si el documento ya existe en nuestra DB
                doc_in_db = session.exec(
                    select(FinancialDocument).where(
                        FinancialDocument.qbo_id == linked_id)
                ).first()

                if doc_in_db:
                    upsert_financial_link(
                        session, doc_in_db.ID_FinancialDoc, trans_obj.ID_FTransaction, dry_run)
                    # Recalcular es una operación local, es rápida.
                    recalculate_document_from_db(session, linked_id)


def _handle_bill(session, entity, realm_id, dry_run):
    """Procesa Bills (Facturas de Proveedores)"""
    mapped_doc = map_entity(entity, QBO_FDOC_FIELD_MAP)
    mapped_doc = attach_job_code(mapped_doc)

    mapped_doc["Percentage_Paid"] = calculate_percentage_paid(
        mapped_doc.get("Total_Amount"),
        mapped_doc.get("Balance_Amount")
    )

    doc_obj, _ = upsert_financial_document(
        session=session,
        data=mapped_doc,
        doc_type=DocumentType.Bill,
        dry_run=dry_run
    )

    if doc_obj and not dry_run:
        # Se borran todos los items actuales de ESTE documento antes de reinsertar
        session.exec(
            delete(FinancialDoc_Item).where(
                FinancialDoc_Item.ID_FinancialDoc == doc_obj.ID_FinancialDoc)
        )
        # Se buscan los items y se actualiza
        for line in entity.get("Line", []):
            if line.get("DetailType") == "ItemBasedExpenseLineDetail":
                mapped_item = map_entity(line, QBO_FDOCITEM_BILL_FIELD_MAP)
                upsert_financial_doc_items(
                    session, mapped_item, doc_obj.ID_FinancialDoc, dry_run)


def _handle_bill_payment(session, entity, dry_run):
    """Procesa Pagos a Proveedores"""
    mapped_trans = map_entity(entity, QBO_FTRANS_BILL_FIELD_MAP)

    trans_obj, _ = upsert_financial_transaction(
        session=session,
        data=mapped_trans,
        trans_type=TransactionType.Bill_payments,
        dry_run=dry_run
    )

    if trans_obj:
        for line in entity.get("Line", []):
            # En BillPayment, las líneas contienen los links a los Bills
            for linked in line.get("LinkedTxn", []):
                linked_id = linked.get("TxnId")

                # Buscamos el Bill en nuestra DB para crear el link
                doc_in_db = session.exec(
                    select(FinancialDocument).where(
                        FinancialDocument.qbo_id == linked_id
                    )
                ).first()

                if doc_in_db:
                    upsert_financial_link(
                        session, doc_in_db.ID_FinancialDoc, trans_obj.ID_FTransaction, dry_run)
                    # Actualizamos el balance del Bill localmente
                    recalculate_document_from_db(session, linked_id)
