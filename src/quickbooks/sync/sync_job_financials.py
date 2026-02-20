
from .sync_invoices_with_payments import sync_qbo_invoices_and_payments_by_job
from .sync_bills_with_payments import sync_qbo_bills_and_payments_by_job


# -------------------------- SINCRONIZAR GLOBAL POR JOB -------------------------- #


def sync_job_financials(realm_id, job_code, start, limit, dry_run):
    print(f"\n🚀 INICIANDO SINCRONIZACIÓN TOTAL - Job: {job_code}")
    print("-" * 50)

    # --- FASE 1: INVOICES ---
    print(f"🔍 [1/4] Buscando Invoices en QBO para {job_code}...")
    try:
        invoice_result = sync_qbo_invoices_and_payments_by_job(
            realm_id, job_code, start, limit, dry_run)
        print(f"✅ Invoices procesadas: {invoice_result.get('synced', 0)}")
    except Exception as e:
        print(f"❌ ERROR en fase de Invoices: {str(e)}")
        invoice_result = {"error": str(e), "synced": 0}

    # --- FASE 2: BILLS ---
    print(f"🔍 [2/4] Buscando Bills en QBO para {job_code}...")
    try:
        bill_result = sync_qbo_bills_and_payments_by_job(
            realm_id, job_code, start, limit, dry_run)
        print(f"✅ Bills procesados: {bill_result.get('synced', 0)}")
    except Exception as e:
        print(f"❌ ERROR en fase de Bills: {str(e)}")
        bill_result = {"error": str(e), "synced": 0}

    # --- FASE 3: RESUMEN FINAL ---
    total = invoice_result.get('synced', 0) + bill_result.get('synced', 0)
    print("-" * 50)
    print(f"🏁 SINCRONIZACIÓN FINALIZADA - Total registros: {total}")

    return {
        "invoices": invoice_result,
        "bills": bill_result
    }
