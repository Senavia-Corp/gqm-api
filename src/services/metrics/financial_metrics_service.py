# src/services/metrics/financial_metrics_service.py
from __future__ import annotations

from sqlmodel import select
from sqlalchemy import func, extract, and_, case
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from ...database.db_sqlmodel import get_session
from ...models.FinancialDocModel import FinancialDocument, DocumentType
from ...models.FinancialTransModel import FinancialTransaction, TransactionType
from ...models.link_models.FinancialLink import FinancialLink
from ...models.JobModel import Job

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

VALID_YEARS = (2026,)          # extend as needed
VALID_DOC_TYPES = ("invoices", "bills", "invoice_payments", "bill_payments", "all")


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def _norm_job_type(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().upper()
    if v in ("ALL", "QID", "PTL", "PAR"):
        return v
    return None


def _norm_year(value: str | None) -> int | None:
    if not value or str(value).upper() == "ALL":
        return None
    try:
        y = int(value)
    except (ValueError, TypeError):
        return None
    if y < 1900 or y > 2100:
        return None
    return y


def _norm_month(value: str | None) -> int | None:
    if not value or str(value).upper() == "ALL":
        return None
    try:
        m = int(value)
    except (ValueError, TypeError):
        return None
    if m < 1 or m > 12:
        return None
    return m


def _norm_doc_type(value: str | None) -> str:
    if not value:
        return "all"
    v = value.strip().lower()
    return v if v in VALID_DOC_TYPES else "all"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_money(v: float) -> str:
    return f"${v:,.2f}"


def _apply_job_type_filter(stmt, job_type: str):
    if job_type != "ALL":
        stmt = stmt.where(Job.Job_type == job_type)
    return stmt


def _apply_doc_date_filters(stmt, year: int | None, month: int | None):
    """Filter FinancialDocument by Due_Date."""
    if year is not None:
        stmt = stmt.where(
            FinancialDocument.Due_Date.is_not(None),
            extract("year", FinancialDocument.Due_Date) == year,
        )
    if month is not None:
        stmt = stmt.where(
            FinancialDocument.Due_Date.is_not(None),
            extract("month", FinancialDocument.Due_Date) == month,
        )
    return stmt


def _apply_trans_date_filters(stmt, year: int | None, month: int | None):
    """Filter FinancialTransaction by Date_of_payment."""
    if year is not None:
        stmt = stmt.where(
            FinancialTransaction.Date_of_payment.is_not(None),
            extract("year", FinancialTransaction.Date_of_payment) == year,
        )
    if month is not None:
        stmt = stmt.where(
            FinancialTransaction.Date_of_payment.is_not(None),
            extract("month", FinancialTransaction.Date_of_payment) == month,
        )
    return stmt


# ---------------------------------------------------------------------------
# Core data fetching
# ---------------------------------------------------------------------------

def _fetch_documents(
    session,
    doc_type: DocumentType,
    job_type: str,
    year: int | None,
    month: int | None,
) -> list[dict]:
    stmt = (
        select(FinancialDocument)
        .options(
            joinedload(FinancialDocument.job),
            joinedload(FinancialDocument.financial_transactions),
        )
        .join(Job, Job.ID_Jobs == FinancialDocument.ID_Jobs, isouter=False)
        .where(FinancialDocument.Type_of_document == doc_type)
    )
    stmt = _apply_job_type_filter(stmt, job_type)
    stmt = _apply_doc_date_filters(stmt, year, month)
    stmt = stmt.order_by(FinancialDocument.Due_Date.asc().nullslast())

    results = session.exec(stmt).unique().all()

    rows = []
    for doc in results:
        job = doc.job
        rows.append({
            "id": doc.ID_FinancialDoc,
            "job_id": doc.ID_Jobs,
            "job_type": job.Job_type if job else None,
            "job_ref_qbo": doc.Job_Ref_QBO,
            "vendor_customer": doc.Vendor_Customer,
            "due_date": str(doc.Due_Date) if doc.Due_Date else None,
            "total_amount": float(doc.Total_Amount or 0),
            "balance_amount": float(doc.Balance_Amount or 0),
            "pct_paid": float(doc.Percentage_Paid or 0),
            "is_voided": doc.is_voided or False,
            "notes": doc.Notes,
            "payment_count": len(doc.financial_transactions),
        })
    return rows


def _fetch_transactions(
    session,
    trans_type: TransactionType,
    job_type: str,
    year: int | None,
    month: int | None,
) -> list[dict]:
    """
    Payments live in financial_transaction; they link to financial_document
    via the M2M FinancialLink table. We join through that to filter by job type.
    """
    stmt = (
        select(FinancialTransaction)
        .join(
            FinancialLink,
            FinancialLink.ftransaction_id == FinancialTransaction.ID_FTransaction,
        )
        .join(
            FinancialDocument,
            FinancialDocument.ID_FinancialDoc == FinancialLink.fdocument_id,
        )
        .join(Job, Job.ID_Jobs == FinancialDocument.ID_Jobs, isouter=False)
        .where(FinancialTransaction.Type_of_transaction == trans_type)
        .where(FinancialTransaction.is_voided.is_(False) | FinancialTransaction.is_voided.is_(None))
    )
    stmt = _apply_job_type_filter(stmt, job_type)
    stmt = _apply_trans_date_filters(stmt, year, month)
    stmt = stmt.distinct()
    stmt = stmt.order_by(FinancialTransaction.Date_of_payment.asc().nullslast())

    results = session.exec(stmt).unique().all()

    rows = []
    for tx in results:
        rows.append({
            "id": tx.ID_FTransaction,
            "reference_number": tx.Reference_number,
            "date_of_payment": str(tx.Date_of_payment) if tx.Date_of_payment else None,
            "total_amount": float(tx.Total_Amount or 0),
            "type_of_payment": tx.Type_of_payment,
            "bank_account_ref": tx.Bank_Account_Ref,
            "is_voided": tx.is_voided or False,
        })
    return rows


def _build_monthly_breakdown(
    invoices: list[dict],
    bills: list[dict],
    inv_payments: list[dict],
    bill_payments: list[dict],
) -> list[dict]:
    """
    Groups all data by month (1–12) using the appropriate date field.
    Returns rows sorted by month number.
    """
    months: dict[int, dict] = {}

    def _ensure(m: int):
        if m not in months:
            months[m] = {
                "month": m,
                "month_name": MONTH_NAMES[m],
                "invoices_due": 0.0,
                "bills_due": 0.0,
                "invoice_payments": 0.0,
                "bill_payments": 0.0,
            }

    for doc in invoices:
        if doc["due_date"]:
            try:
                m = int(doc["due_date"][5:7])
                _ensure(m)
                months[m]["invoices_due"] += doc["total_amount"]
            except Exception:
                pass

    for doc in bills:
        if doc["due_date"]:
            try:
                m = int(doc["due_date"][5:7])
                _ensure(m)
                months[m]["bills_due"] += doc["total_amount"]
            except Exception:
                pass

    for tx in inv_payments:
        if tx["date_of_payment"]:
            try:
                m = int(tx["date_of_payment"][5:7])
                _ensure(m)
                months[m]["invoice_payments"] += tx["total_amount"]
            except Exception:
                pass

    for tx in bill_payments:
        if tx["date_of_payment"]:
            try:
                m = int(tx["date_of_payment"][5:7])
                _ensure(m)
                months[m]["bill_payments"] += tx["total_amount"]
            except Exception:
                pass

    return sorted(months.values(), key=lambda x: x["month"])


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------

def get_financial_metrics_data(
    job_type_raw: str | None,
    year_raw: str | None,
    month_raw: str | None,
    doc_type_raw: str | None,
) -> tuple[dict | None, tuple | None]:
    """
    Returns (data_dict, error_tuple).
    error_tuple is (payload_dict, http_status) or None if OK.
    """
    job_type = _norm_job_type(job_type_raw)
    if job_type is None:
        return None, ({"detail": "Invalid type. Use QID, PTL, PAR or ALL."}, 400)

    year = _norm_year(year_raw)
    if year_raw is not None and str(year_raw).upper() != "ALL" and year is None:
        return None, ({"detail": "Invalid year."}, 400)

    month = _norm_month(month_raw)
    if month_raw is not None and str(month_raw).upper() != "ALL" and month is None:
        return None, ({"detail": "Invalid month. Use 1-12 or ALL."}, 400)

    doc_type = _norm_doc_type(doc_type_raw)

    try:
        with get_session() as session:
            # Always fetch all four sets (needed for summary + monthly breakdown)
            invoices     = _fetch_documents(session, DocumentType.Invoice, job_type, year, month)
            bills        = _fetch_documents(session, DocumentType.Bill,    job_type, year, month)
            inv_payments = _fetch_transactions(session, TransactionType.Invoice_payments, job_type, year, month)
            bill_payments = _fetch_transactions(session, TransactionType.Bill_payments,  job_type, year, month)

        # --- Summary KPIs ---
        total_invoiced   = sum(d["total_amount"] for d in invoices)
        total_billed     = sum(d["total_amount"] for d in bills)
        inv_balance      = sum(d["balance_amount"] for d in invoices)
        bill_balance     = sum(d["balance_amount"] for d in bills)
        total_inv_paid   = sum(t["total_amount"] for t in inv_payments)
        total_bill_paid  = sum(t["total_amount"] for t in bill_payments)
        total_collected  = total_inv_paid + total_bill_paid
        total_outstanding = inv_balance + bill_balance

        avg_inv_pct = (
            sum(d["pct_paid"] for d in invoices) / len(invoices)
            if invoices else 0.0
        )
        avg_bill_pct = (
            sum(d["pct_paid"] for d in bills) / len(bills)
            if bills else 0.0
        )

        summary = {
            "total_invoiced":    round(total_invoiced, 2),
            "total_billed":      round(total_billed, 2),
            "total_collected":   round(total_collected, 2),
            "total_outstanding": round(total_outstanding, 2),
            "invoice_balance":   round(inv_balance, 2),
            "bill_balance":      round(bill_balance, 2),
            "inv_payment_total": round(total_inv_paid, 2),
            "bill_payment_total":round(total_bill_paid, 2),
            "avg_invoice_pct_paid":  round(avg_inv_pct, 2),
            "avg_bill_pct_paid":     round(avg_bill_pct, 2),
            "invoice_count":     len(invoices),
            "bill_count":        len(bills),
            "inv_payment_count": len(inv_payments),
            "bill_payment_count":len(bill_payments),
        }

        monthly = _build_monthly_breakdown(invoices, bills, inv_payments, bill_payments)

        # --- Respect doc_type filter for detail sections ---
        data = {
            "filters": {
                "type":     job_type,
                "year":     year,
                "month":    month,
                "doc_type": doc_type,
            },
            "summary": summary,
            "monthly_breakdown": monthly,
            "invoices":      invoices      if doc_type in ("all", "invoices")          else [],
            "bills":         bills         if doc_type in ("all", "bills")             else [],
            "inv_payments":  inv_payments  if doc_type in ("all", "invoice_payments")  else [],
            "bill_payments": bill_payments if doc_type in ("all", "bill_payments")     else [],
        }

        return data, None

    except SQLAlchemyError as e:
        return None, ({"detail": "DB error.", "code": "db_error", "info": str(e)}, 500)
    except Exception as e:
        return None, ({"detail": "Unexpected error.", "code": "internal_error", "info": str(e)}, 500)