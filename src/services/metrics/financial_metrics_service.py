from __future__ import annotations

from datetime import date
from sqlmodel import select
from sqlalchemy import extract, func
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

VALID_DOC_TYPES = ("invoices", "bills", "invoice_payments",
                   "bill_payments", "all")


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
# Document status classification
# ---------------------------------------------------------------------------

def _classify_doc_status(total: float, balance: float, due_date: str | None, is_voided: bool) -> str:
    """
    Status is based on current Balance_Amount from QBO — reflects real-time
    state of the document regardless of period filters.
    """
    if is_voided:
        return "Voided"
    if balance <= 0:
        return "Paid"
    if balance >= total:
        if due_date:
            try:
                d = date.fromisoformat(due_date)
                if d < date.today():
                    return "Overdue"
            except ValueError:
                pass
        return "Pending"
    if due_date:
        try:
            d = date.fromisoformat(due_date)
            if d < date.today():
                return "Overdue"
        except ValueError:
            pass
    return "Partial"


# ---------------------------------------------------------------------------
# Aging bucket classification
# ---------------------------------------------------------------------------

def _aging_bucket(due_date: str | None, balance: float) -> str | None:
    if balance <= 0:
        return None
    if not due_date:
        return "No Due Date"
    try:
        d = date.fromisoformat(due_date)
    except ValueError:
        return "No Due Date"

    days_overdue = (date.today() - d).days

    if days_overdue <= 0:
        return "Current"
    elif days_overdue <= 30:
        return "1–30 days"
    elif days_overdue <= 60:
        return "31–60 days"
    elif days_overdue <= 90:
        return "61–90 days"
    else:
        return "+90 days"


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


# ---------------------------------------------------------------------------
# amount_applied subquery filtered by payment period
# ---------------------------------------------------------------------------

def _build_amount_applied_subquery(year: int | None, month: int | None):

    # Subquery that sums amount_applied per document filtered by date_applied.
    sq = (
        select(
            FinancialLink.fdocument_id,
            func.coalesce(func.sum(FinancialLink.amount_applied),
                          0).label("period_collected"),
        )
        .group_by(FinancialLink.fdocument_id)
    )

    if year is not None:
        sq = sq.where(
            (FinancialLink.date_applied.is_(None)) |
            (extract("year", FinancialLink.date_applied) == year)
        )
    if month is not None:
        sq = sq.where(
            (FinancialLink.date_applied.is_(None)) |
            (extract("month", FinancialLink.date_applied) == month)
        )

    return sq.subquery()


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

    # Fetches documents with period_collected from FinancialLink.amount_applied.
    amount_sq = _build_amount_applied_subquery(year, month)

    stmt = (
        select(FinancialDocument, amount_sq.c.period_collected)
        .options(
            joinedload(FinancialDocument.job),
            joinedload(FinancialDocument.financial_transactions),
        )
        .join(Job, Job.ID_Jobs == FinancialDocument.ID_Jobs, isouter=False)
        .outerjoin(amount_sq, amount_sq.c.fdocument_id == FinancialDocument.ID_FinancialDoc)
        .where(FinancialDocument.Type_of_document == doc_type)
    )
    stmt = _apply_job_type_filter(stmt, job_type)
    stmt = _apply_doc_date_filters(stmt, year, month)
    stmt = stmt.order_by(FinancialDocument.Due_Date.asc().nullslast())

    results = session.exec(stmt).unique().all()

    rows = []
    for row in results:
        if isinstance(row, tuple):
            doc, period_collected = row
        else:
            doc = row
            period_collected = None

        job = doc.job
        total = float(doc.Total_Amount or 0)
        balance = float(doc.Balance_Amount or 0)

        # Use amount_applied sum for the period; fall back to Total - Balance
        # for documents whose links predate the migration (no amount_applied)
        collected_in_period = float(period_collected or 0)
        if collected_in_period == 0 and balance < total:
            collected_in_period = round(total - balance, 2)

        due_date_str = str(doc.Due_Date) if doc.Due_Date else None
        is_voided = doc.is_voided or False

        status = _classify_doc_status(total, balance, due_date_str, is_voided)
        aging = _aging_bucket(due_date_str, balance)

        rows.append({
            "id":               doc.ID_FinancialDoc,
            "job_id":           doc.ID_Jobs,
            "job_type":         job.Job_type if job else None,
            "job_ref_qbo":      doc.Job_Ref_QBO,
            "vendor_customer":  doc.Vendor_Customer,
            "due_date":         due_date_str,
            "total_amount":     total,
            "balance_amount":   balance,
            "collected_amount": round(collected_in_period, 2),
            "pct_paid":         float(doc.Percentage_Paid or 0),
            "is_voided":        is_voided,
            "status":           status,
            "aging_bucket":     aging,
            "notes":            doc.Notes,
            "payment_count":    len(doc.financial_transactions),
        })
    return rows


def _fetch_transactions(
    session,
    trans_type: TransactionType,
    job_type: str,
    year: int | None,
    month: int | None,
) -> list[dict]:

    # Fetches payment transactions for display only.
    # Filtered by date_applied on the link (actual payment period).
    stmt = (
        select(FinancialTransaction)
        .join(FinancialLink, FinancialLink.ftransaction_id == FinancialTransaction.ID_FTransaction)
        .join(FinancialDocument, FinancialDocument.ID_FinancialDoc == FinancialLink.fdocument_id)
        .join(Job, Job.ID_Jobs == FinancialDocument.ID_Jobs, isouter=False)
        .where(FinancialTransaction.Type_of_transaction == trans_type)
        .where(
            FinancialTransaction.is_voided.is_(False) |
            FinancialTransaction.is_voided.is_(None)
        )
    )
    stmt = _apply_job_type_filter(stmt, job_type)

    if year is not None:
        stmt = stmt.where(
            (FinancialLink.date_applied.is_(None)) |
            (extract("year", FinancialLink.date_applied) == year)
        )
    if month is not None:
        stmt = stmt.where(
            (FinancialLink.date_applied.is_(None)) |
            (extract("month", FinancialLink.date_applied) == month)
        )

    stmt = stmt.distinct()
    stmt = stmt.order_by(
        FinancialTransaction.Date_of_payment.asc().nullslast())

    results = session.exec(stmt).unique().all()

    return [
        {
            "id":               tx.ID_FTransaction,
            "reference_number": tx.Reference_number,
            "date_of_payment":  str(tx.Date_of_payment) if tx.Date_of_payment else None,
            "total_amount":     float(tx.Total_Amount or 0),
            "type_of_payment":  tx.Type_of_payment,
            "bank_account_ref": tx.Bank_Account_Ref,
            "is_voided":        tx.is_voided or False,
        }
        for tx in results
    ]


# ---------------------------------------------------------------------------
# Monthly breakdown
# ---------------------------------------------------------------------------

def _build_monthly_breakdown(invoices: list[dict], bills: list[dict]) -> list[dict]:
    """
    Groups by month using Due_Date of the document for totals/balances,
    and collected_amount (from amount_applied) for the collected/paid figures.
    """
    months: dict[int, dict] = {}

    def _ensure(m: int):
        if m not in months:
            months[m] = {
                "month":              m,
                "month_name":         MONTH_NAMES[m],
                "invoices_total":     0.0,
                "invoices_collected": 0.0,
                "invoices_balance":   0.0,
                "bills_total":        0.0,
                "bills_paid":         0.0,
                "bills_balance":      0.0,
                "net_flow":           0.0,
            }

    for doc in invoices:
        if doc["is_voided"] or not doc["due_date"]:
            continue
        try:
            m = int(doc["due_date"][5:7])
            _ensure(m)
            months[m]["invoices_total"] += doc["total_amount"]
            months[m]["invoices_collected"] += doc["collected_amount"]
            months[m]["invoices_balance"] += doc["balance_amount"]
        except Exception:
            pass

    for doc in bills:
        if doc["is_voided"] or not doc["due_date"]:
            continue
        try:
            m = int(doc["due_date"][5:7])
            _ensure(m)
            months[m]["bills_total"] += doc["total_amount"]
            months[m]["bills_paid"] += doc["collected_amount"]
            months[m]["bills_balance"] += doc["balance_amount"]
        except Exception:
            pass

    for m_data in months.values():
        for key in ["invoices_total", "invoices_collected", "invoices_balance",
                    "bills_total", "bills_paid", "bills_balance"]:
            m_data[key] = round(m_data[key], 2)
        m_data["net_flow"] = round(
            m_data["invoices_collected"] - m_data["bills_paid"], 2)

    return sorted(months.values(), key=lambda x: x["month"])


# ---------------------------------------------------------------------------
# Aging report
# ---------------------------------------------------------------------------

AGING_BUCKETS_ORDER = ["Current", "1–30 days",
                       "31–60 days", "61–90 days", "+90 days", "No Due Date"]


def _build_aging_report(invoices: list[dict], bills: list[dict]) -> dict:
    inv_aging:   dict[str, float] = {b: 0.0 for b in AGING_BUCKETS_ORDER}
    bill_aging:  dict[str, float] = {b: 0.0 for b in AGING_BUCKETS_ORDER}
    inv_counts:  dict[str, int] = {b: 0 for b in AGING_BUCKETS_ORDER}
    bill_counts: dict[str, int] = {b: 0 for b in AGING_BUCKETS_ORDER}

    for doc in invoices:
        bucket = doc.get("aging_bucket")
        if bucket and bucket in inv_aging:
            inv_aging[bucket] += doc["balance_amount"]
            inv_counts[bucket] += 1

    for doc in bills:
        bucket = doc.get("aging_bucket")
        if bucket and bucket in bill_aging:
            bill_aging[bucket] += doc["balance_amount"]
            bill_counts[bucket] += 1

    rows = [
        {
            "bucket":       bucket,
            "inv_balance":  round(inv_aging[bucket],  2),
            "inv_count":    inv_counts[bucket],
            "bill_balance": round(bill_aging[bucket], 2),
            "bill_count":   bill_counts[bucket],
            "total":        round(inv_aging[bucket] + bill_aging[bucket], 2),
        }
        for bucket in AGING_BUCKETS_ORDER
        if inv_aging[bucket] > 0 or bill_aging[bucket] > 0
    ]

    return {
        "rows":               rows,
        "total_inv_overdue":  round(sum(inv_aging[b] for b in AGING_BUCKETS_ORDER if b != "Current"), 2),
        "total_bill_overdue": round(sum(bill_aging[b] for b in AGING_BUCKETS_ORDER if b != "Current"), 2),
        "total_overdue":      round(sum(
            inv_aging[b] + bill_aging[b] for b in AGING_BUCKETS_ORDER if b != "Current"
        ), 2),
    }


# ---------------------------------------------------------------------------
# Job breakdown
# ---------------------------------------------------------------------------

def _build_job_breakdown(invoices: list[dict], bills: list[dict]) -> list[dict]:
    jobs: dict[str, dict] = {}

    def _ensure_job(job_id: str, job_type: str | None):
        if job_id not in jobs:
            jobs[job_id] = {
                "job_id":        job_id,
                "job_type":      job_type,
                "inv_total":     0.0,
                "inv_collected": 0.0,
                "inv_balance":   0.0,
                "inv_count":     0,
                "bill_total":    0.0,
                "bill_paid":     0.0,
                "bill_balance":  0.0,
                "bill_count":    0,
                "gross_profit":  0.0,
                "status":        "OK",
            }

    for doc in invoices:
        if doc["is_voided"]:
            continue
        jid = doc["job_id"] or "No Job"
        _ensure_job(jid, doc.get("job_type"))
        jobs[jid]["inv_total"] += doc["total_amount"]
        jobs[jid]["inv_collected"] += doc["collected_amount"]
        jobs[jid]["inv_balance"] += doc["balance_amount"]
        jobs[jid]["inv_count"] += 1

    for doc in bills:
        if doc["is_voided"]:
            continue
        jid = doc["job_id"] or "No Job"
        _ensure_job(jid, doc.get("job_type"))
        jobs[jid]["bill_total"] += doc["total_amount"]
        jobs[jid]["bill_paid"] += doc["collected_amount"]
        jobs[jid]["bill_balance"] += doc["balance_amount"]
        jobs[jid]["bill_count"] += 1

    result = []
    for j in jobs.values():
        for key in ["inv_total", "inv_collected", "inv_balance",
                    "bill_total", "bill_paid", "bill_balance"]:
            j[key] = round(j[key], 2)
        j["gross_profit"] = round(j["inv_collected"] - j["bill_paid"], 2)

        has_overdue_inv = any(
            d["aging_bucket"] not in (
                None, "Current") and d["job_id"] == j["job_id"]
            for d in invoices
        )
        has_overdue_bill = any(
            d["aging_bucket"] not in (
                None, "Current") and d["job_id"] == j["job_id"]
            for d in bills
        )

        if has_overdue_inv or has_overdue_bill:
            j["status"] = "Overdue"
        elif j["inv_balance"] > 0 or j["bill_balance"] > 0:
            j["status"] = "Partial"
        else:
            j["status"] = "Settled"

        result.append(j)

    return sorted(result, key=lambda x: x["job_id"])


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

    collected_amount uses sum(FinancialLink.amount_applied) filtered by date_applied,
    preventing inflation from payments made in other periods.
    Falls back to Total - Balance for legacy links without amount_applied.
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
            invoices = _fetch_documents(
                session, DocumentType.Invoice, job_type, year, month)
            bills = _fetch_documents(
                session, DocumentType.Bill,    job_type, year, month)
            inv_payments = _fetch_transactions(
                session, TransactionType.Invoice_payments, job_type, year, month)
            bill_payments = _fetch_transactions(
                session, TransactionType.Bill_payments,    job_type, year, month)

        active_invoices = [d for d in invoices if not d["is_voided"]]
        active_bills = [d for d in bills if not d["is_voided"]]

        total_invoiced = sum(d["total_amount"] for d in active_invoices)
        total_billed = sum(d["total_amount"] for d in active_bills)
        inv_collected = sum(d["collected_amount"] for d in active_invoices)
        bill_paid = sum(d["collected_amount"] for d in active_bills)
        inv_balance = sum(d["balance_amount"] for d in active_invoices)
        bill_balance = sum(d["balance_amount"] for d in active_bills)
        net_flow = round(inv_collected - bill_paid, 2)
        total_outstanding = round(inv_balance + bill_balance, 2)

        inv_status_counts = {"Paid": 0, "Partial": 0,
                             "Pending": 0, "Overdue": 0, "Voided": 0}
        bill_status_counts = {"Paid": 0, "Partial": 0,
                              "Pending": 0, "Overdue": 0, "Voided": 0}

        for d in invoices:
            if d["status"] in inv_status_counts:
                inv_status_counts[d["status"]] += 1

        for d in bills:
            if d["status"] in bill_status_counts:
                bill_status_counts[d["status"]] += 1

        avg_inv_pct = (sum(d["pct_paid"] for d in active_invoices) / len(active_invoices)
                       if active_invoices else 0.0)
        avg_bill_pct = (sum(d["pct_paid"] for d in active_bills) / len(active_bills)
                        if active_bills else 0.0)

        summary = {
            "total_invoiced":       round(total_invoiced, 2),
            "inv_collected":        round(inv_collected,  2),
            "inv_balance":          round(inv_balance,    2),
            "avg_invoice_pct_paid": round(avg_inv_pct,    2),
            "invoice_count":        len(active_invoices),
            "inv_status_counts":    inv_status_counts,
            "total_billed":         round(total_billed,  2),
            "bill_paid":            round(bill_paid,     2),
            "bill_balance":         round(bill_balance,  2),
            "avg_bill_pct_paid":    round(avg_bill_pct,  2),
            "bill_count":           len(active_bills),
            "bill_status_counts":   bill_status_counts,
            "net_flow":             net_flow,
            "total_outstanding":    total_outstanding,
            "inv_payment_count":    len(inv_payments),
            "bill_payment_count":   len(bill_payments),
        }

        monthly = _build_monthly_breakdown(invoices, bills)
        aging = _build_aging_report(invoices, bills)
        job_breakdown = _build_job_breakdown(invoices, bills)

        data = {
            "filters": {
                "type":     job_type,
                "year":     year,
                "month":    month,
                "doc_type": doc_type,
            },
            "summary":           summary,
            "monthly_breakdown": monthly,
            "aging_report":      aging,
            "job_breakdown":     job_breakdown,
            "invoices":      invoices if doc_type in ("all", "invoices") else [],
            "bills":         bills if doc_type in ("all", "bills") else [],
            "inv_payments":  inv_payments if doc_type in ("all", "invoice_payments") else [],
            "bill_payments": bill_payments if doc_type in ("all", "bill_payments") else [],
        }

        return data, None

    except SQLAlchemyError as e:
        return None, ({"detail": "DB error.", "code": "db_error", "info": str(e)}, 500)
    except Exception as e:
        return None, ({"detail": "Unexpected error.", "code": "internal_error", "info": str(e)}, 500)
