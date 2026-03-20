# test_financial_report.py
# Corre este script desde la raíz del proyecto:
#   python test_financial_report.py
# Genera: financial_report_TEST.pdf en el mismo directorio

from datetime import date, timedelta
import sys
import os

# ---------------------------------------------------------------------------
# Si tu proyecto usa imports relativos, agrega el src al path así:
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
# ---------------------------------------------------------------------------

from src.services.reports.financial_report_pdf import build_financial_report_pdf_bytes


# ---------------------------------------------------------------------------
# Mock data — simula la salida de get_financial_metrics_data()
# ---------------------------------------------------------------------------

today = date.today()


def days_ago(n): return str(today - timedelta(days=n))
def days_from_now(n): return str(today + timedelta(days=n))


MOCK_DATA = {
    "filters": {
        "type":     "ALL",
        "year":     2026,
        "month":    None,
        "doc_type": "all",
    },

    # ------------------------------------------------------------------
    # Summary — usa Total - Balance como fuente de verdad
    # ------------------------------------------------------------------
    "summary": {
        # Revenue
        "total_invoiced":       185_000.00,
        "inv_collected":        132_500.00,
        "inv_balance":           52_500.00,
        "avg_invoice_pct_paid":  71.6,
        "invoice_count":         8,
        "inv_status_counts": {
            "Paid": 3, "Partial": 2, "Pending": 1, "Overdue": 2, "Voided": 0
        },
        # Expenses
        "total_billed":          97_400.00,
        "bill_paid":             78_200.00,
        "bill_balance":          19_200.00,
        "avg_bill_pct_paid":     80.3,
        "bill_count":            6,
        "bill_status_counts": {
            "Paid": 3, "Partial": 2, "Pending": 0, "Overdue": 1, "Voided": 0
        },
        # Net
        "net_flow":              54_300.00,   # inv_collected - bill_paid
        "total_outstanding":     71_700.00,   # inv_balance + bill_balance
        # Transactions (display only)
        "inv_payment_count":     11,
        "bill_payment_count":     7,
    },

    # ------------------------------------------------------------------
    # Monthly breakdown — agrupado por Due_Date del documento
    # ------------------------------------------------------------------
    "monthly_breakdown": [
        {
            "month": 1, "month_name": "January",
            "invoices_total": 32000, "invoices_collected": 32000, "invoices_balance": 0,
            "bills_total": 14000,   "bills_paid": 14000,          "bills_balance": 0,
            "net_flow": 18000,
        },
        {
            "month": 2, "month_name": "February",
            "invoices_total": 45000, "invoices_collected": 38000, "invoices_balance": 7000,
            "bills_total": 22000,   "bills_paid": 20000,          "bills_balance": 2000,
            "net_flow": 18000,
        },
        {
            "month": 3, "month_name": "March",
            "invoices_total": 58000, "invoices_collected": 42500, "invoices_balance": 15500,
            "bills_total": 31400,   "bills_paid": 24200,          "bills_balance": 7200,
            "net_flow": 18300,
        },
        {
            "month": 4, "month_name": "April",
            "invoices_total": 50000, "invoices_collected": 20000, "invoices_balance": 30000,
            "bills_total": 30000,   "bills_paid": 20000,          "bills_balance": 10000,
            "net_flow": 0,
        },
    ],

    # ------------------------------------------------------------------
    # Aging report
    # ------------------------------------------------------------------
    "aging_report": {
        "rows": [
            {"bucket": "Current",    "inv_balance": 30000, "inv_count": 1,
                "bill_balance": 10000, "bill_count": 1, "total": 40000},
            {"bucket": "1–30 days",  "inv_balance":  8500, "inv_count": 1,
                "bill_balance":  4200, "bill_count": 1, "total": 12700},
            {"bucket": "31–60 days", "inv_balance":  7000, "inv_count": 1,
                "bill_balance":  5000, "bill_count": 1, "total": 12000},
            {"bucket": "+90 days",   "inv_balance":  7000, "inv_count": 1,
                "bill_balance":     0, "bill_count": 0, "total":  7000},
        ],
        "total_inv_overdue":  22500,
        "total_bill_overdue":  9200,
        "total_overdue":      31700,
    },

    # ------------------------------------------------------------------
    # Job breakdown
    # ------------------------------------------------------------------
    "job_breakdown": [
        {
            "job_id": "QID-001", "job_type": "QID",
            "inv_total": 32000, "inv_collected": 32000, "inv_balance": 0,
            "bill_total": 14000, "bill_paid": 14000,   "bill_balance": 0,
            "net_margin": 18000, "inv_count": 1, "bill_count": 1, "status": "Settled",
        },
        {
            "job_id": "QID-002", "job_type": "QID",
            "inv_total": 45000, "inv_collected": 38000, "inv_balance": 7000,
            "bill_total": 22000, "bill_paid": 20000,    "bill_balance": 2000,
            "net_margin": 18000, "inv_count": 2, "bill_count": 1, "status": "Partial",
        },
        {
            "job_id": "PTL-010", "job_type": "PTL",
            "inv_total": 58000, "inv_collected": 42500, "inv_balance": 15500,
            "bill_total": 31400, "bill_paid": 24200,    "bill_balance": 7200,
            "net_margin": 18300, "inv_count": 2, "bill_count": 2, "status": "Overdue",
        },
        {
            "job_id": "PAR-005", "job_type": "PAR",
            "inv_total": 50000, "inv_collected": 20000, "inv_balance": 30000,
            "bill_total": 30000, "bill_paid": 20000,    "bill_balance": 10000,
            "net_margin": 0, "inv_count": 3, "bill_count": 2, "status": "Overdue",
        },
    ],

    # ------------------------------------------------------------------
    # Invoices detail
    # ------------------------------------------------------------------
    "invoices": [
        {
            "id": "FD-001", "job_id": "QID-001", "job_type": "QID",
            "job_ref_qbo": "INV-1001", "vendor_customer": "Acme Corp",
            "due_date": days_ago(90), "total_amount": 32000, "balance_amount": 0,
            "collected_amount": 32000, "pct_paid": 100.0,
            "is_voided": False, "status": "Paid", "aging_bucket": None, "notes": None, "payment_count": 2,
        },
        {
            "id": "FD-002", "job_id": "QID-002", "job_type": "QID",
            "job_ref_qbo": "INV-1002", "vendor_customer": "BuildRight LLC",
            "due_date": days_ago(45), "total_amount": 25000, "balance_amount": 7000,
            "collected_amount": 18000, "pct_paid": 72.0,
            "is_voided": False, "status": "Overdue", "aging_bucket": "31–60 days", "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-003", "job_id": "QID-002", "job_type": "QID",
            "job_ref_qbo": "INV-1003", "vendor_customer": "BuildRight LLC",
            "due_date": days_ago(20), "total_amount": 20000, "balance_amount": 0,
            "collected_amount": 20000, "pct_paid": 100.0,
            "is_voided": False, "status": "Paid", "aging_bucket": None, "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-004", "job_id": "PTL-010", "job_type": "PTL",
            "job_ref_qbo": "INV-1004", "vendor_customer": "Skyline Ventures",
            "due_date": days_ago(100), "total_amount": 28000, "balance_amount": 8500,
            "collected_amount": 19500, "pct_paid": 69.6,
            "is_voided": False, "status": "Overdue", "aging_bucket": "+90 days", "notes": "Dispute pending", "payment_count": 2,
        },
        {
            "id": "FD-005", "job_id": "PTL-010", "job_type": "PTL",
            "job_ref_qbo": "INV-1005", "vendor_customer": "Skyline Ventures",
            "due_date": days_from_now(15), "total_amount": 30000, "balance_amount": 7000,
            "collected_amount": 23000, "pct_paid": 76.7,
            "is_voided": False, "status": "Partial", "aging_bucket": "Current", "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-006", "job_id": "PAR-005", "job_type": "PAR",
            "job_ref_qbo": "INV-1006", "vendor_customer": "Metro Builders",
            "due_date": days_ago(35), "total_amount": 20000, "balance_amount": 15000,
            "collected_amount": 5000, "pct_paid": 25.0,
            "is_voided": False, "status": "Overdue", "aging_bucket": "31–60 days", "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-007", "job_id": "PAR-005", "job_type": "PAR",
            "job_ref_qbo": "INV-1007", "vendor_customer": "Metro Builders",
            "due_date": days_from_now(30), "total_amount": 18000, "balance_amount": 9000,
            "collected_amount": 9000, "pct_paid": 50.0,
            "is_voided": False, "status": "Partial", "aging_bucket": "Current", "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-008", "job_id": "PAR-005", "job_type": "PAR",
            "job_ref_qbo": "INV-1008", "vendor_customer": "Metro Builders",
            "due_date": days_from_now(45), "total_amount": 12000, "balance_amount": 6000,
            "collected_amount": 6000, "pct_paid": 50.0,
            "is_voided": False, "status": "Partial", "aging_bucket": "Current", "notes": None, "payment_count": 0,
        },
    ],

    # ------------------------------------------------------------------
    # Bills detail
    # ------------------------------------------------------------------
    "bills": [
        {
            "id": "FD-101", "job_id": "QID-001", "job_type": "QID",
            "job_ref_qbo": "BILL-2001", "vendor_customer": "Steel Supply Co",
            "due_date": days_ago(80), "total_amount": 14000, "balance_amount": 0,
            "collected_amount": 14000, "pct_paid": 100.0,
            "is_voided": False, "status": "Paid", "aging_bucket": None, "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-102", "job_id": "QID-002", "job_type": "QID",
            "job_ref_qbo": "BILL-2002", "vendor_customer": "Concrete Masters",
            "due_date": days_ago(10), "total_amount": 22000, "balance_amount": 2000,
            "collected_amount": 20000, "pct_paid": 90.9,
            "is_voided": False, "status": "Partial", "aging_bucket": "1–30 days", "notes": None, "payment_count": 2,
        },
        {
            "id": "FD-103", "job_id": "PTL-010", "job_type": "PTL",
            "job_ref_qbo": "BILL-2003", "vendor_customer": "Electric Pro LLC",
            "due_date": days_ago(95), "total_amount": 15000, "balance_amount": 5000,
            "collected_amount": 10000, "pct_paid": 66.7,
            "is_voided": False, "status": "Overdue", "aging_bucket": "+90 days", "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-104", "job_id": "PTL-010", "job_type": "PTL",
            "job_ref_qbo": "BILL-2004", "vendor_customer": "Plumbing Works",
            "due_date": days_ago(5), "total_amount": 16400, "balance_amount": 2200,
            "collected_amount": 14200, "pct_paid": 86.6,
            "is_voided": False, "status": "Partial", "aging_bucket": "1–30 days", "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-105", "job_id": "PAR-005", "job_type": "PAR",
            "job_ref_qbo": "BILL-2005", "vendor_customer": "Roofing Experts",
            "due_date": days_ago(3), "total_amount": 18000, "balance_amount": 10000,
            "collected_amount": 8000, "pct_paid": 44.4,
            "is_voided": False, "status": "Pending", "aging_bucket": "Current", "notes": None, "payment_count": 1,
        },
        {
            "id": "FD-106", "job_id": "PAR-005", "job_type": "PAR",
            "job_ref_qbo": "BILL-2006", "vendor_customer": "Interior Designs",
            "due_date": days_from_now(20), "total_amount": 12000, "balance_amount": 0,
            "collected_amount": 12000, "pct_paid": 100.0,
            "is_voided": False, "status": "Paid", "aging_bucket": None, "notes": None, "payment_count": 1,
        },
    ],

    # ------------------------------------------------------------------
    # Invoice payments (referencia visual solamente)
    # ------------------------------------------------------------------
    "inv_payments": [
        {"id": "FT-001", "reference_number": "PMT-5001", "date_of_payment": days_ago(88),
         "total_amount": 32000, "type_of_payment": "Check",       "bank_account_ref": "Chase Business ****1234", "is_voided": False},
        {"id": "FT-002", "reference_number": "PMT-5002", "date_of_payment": days_ago(50),
         "total_amount": 43000, "type_of_payment": "ACH",         "bank_account_ref": "Chase Business ****1234", "is_voided": False},
        {"id": "FT-003", "reference_number": "PMT-5003", "date_of_payment": days_ago(25),
         "total_amount": 28500, "type_of_payment": "Wire",        "bank_account_ref": "Chase Business ****1234", "is_voided": False},
        {"id": "FT-004", "reference_number": "PMT-5004", "date_of_payment": days_ago(10),
         "total_amount": 29000, "type_of_payment": "Credit Card", "bank_account_ref": "Amex ****9876",           "is_voided": False},
    ],

    # ------------------------------------------------------------------
    # Bill payments (referencia visual solamente)
    # ------------------------------------------------------------------
    "bill_payments": [
        {"id": "FT-101", "reference_number": "BP-3001", "date_of_payment": days_ago(79),
         "total_amount": 14000, "type_of_payment": "Check", "bank_account_ref": "Chase Business ****1234", "is_voided": False},
        {"id": "FT-102", "reference_number": "BP-3002", "date_of_payment": days_ago(40),
         "total_amount": 36000, "type_of_payment": "ACH",   "bank_account_ref": "Chase Business ****1234", "is_voided": False},
        {"id": "FT-103", "reference_number": "BP-3003", "date_of_payment": days_ago(8),
         "total_amount": 28200, "type_of_payment": "Wire",  "bank_account_ref": "Chase Business ****1234", "is_voided": False},
    ],
}


# ---------------------------------------------------------------------------
# Genera el PDF
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    output_path = "financial_report_TEST.pdf"

    print("Generando PDF de prueba...")
    pdf_bytes = build_financial_report_pdf_bytes(
        MOCK_DATA,
        company_name="Senavia Corp",
        logo_path="src/assets/gqm-logo.png"
    )

    with open(output_path, "wb") as f:
        f.write(pdf_bytes)

    print(f"✅ PDF generado: {output_path}  ({len(pdf_bytes):,} bytes)")
    print("   Ábrelo con cualquier visor de PDF para revisar el diseño.")
