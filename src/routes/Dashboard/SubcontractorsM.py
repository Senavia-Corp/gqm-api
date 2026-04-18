from __future__ import annotations

from itertools import combinations

from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy import func, and_, extract, or_, literal

from src.database.db_sqlmodel import get_session
from src.models.SubcontractorModel import Subcontractor
from src.models.TechnicianModel import Technician
from src.models.TasksModel import Tasks
from src.models.JobModel import Job
from src.models.SkillsModel import Skills
from src.models.link_models.SkillsSubcontractor import SkillsSubcLink
from src.models.FinancialDocModel import FinancialDocument
from src.models.FinancialTransModel import FinancialTransaction
from src.models.link_models.FinancialLink import FinancialLink
from src.models.OrderModel import Order
from src.services.metrics.aux_func_metrics import _safe_int
from src.services.metrics.jobs_metrics_service import _safe_float
from src.services.metrics.metrics_shared import _norm_year


subcontractor_metrics_bp = Blueprint(
    "subcontractor_metrics_blueprint",
    __name__,
    url_prefix="/subcontractor_metrics",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tasks_overlap(tasks: list[dict]) -> bool:
    """
    Returns True if any two tasks from the same sub have overlapping date ranges.
    Overlap condition: start_A < end_B AND start_B < end_A
    Ignores tasks where either date is None.
    """
    valid = [t for t in tasks if t["start_date"] and t["delivery_date"]]
    for a, b in combinations(valid, 2):
        if a["start_date"] < b["delivery_date"] and b["start_date"] < a["delivery_date"]:
            return True
    return False


def _fmt_date(d) -> str | None:
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else None


_VENDOR_DIRTY_CHARS = str.maketrans("", "", '"{}')


def _clean_org(value: str | None) -> str:
    """
    Strips Podio noise from Organization / Vendor_Customer strings.
    Removes double-quotes, curly braces, and leading/trailing whitespace.
    Example: '{"Acme Corp"}' -> 'Acme Corp'
    """
    if not value:
        return ""
    return value.translate(_VENDOR_DIRTY_CHARS).strip()


def _vendor_col_cleaned():
    """
    PostgreSQL expression that strips Podio noise ('"', '{', '}')
    from FinancialDocument.Vendor_Customer before comparison.
    Whitespace is NOT removed so that ILIKE patterns with spaces work correctly.
    """
    return func.trim(
        func.regexp_replace(
            FinancialDocument.Vendor_Customer,
            r'["{}]+',
            "",
            "g",
        )
    )


def _org_matches_vendor(org_clean: str, vendor_clean: str) -> bool:
    """
    Bidirectional containment check (Python side).
    Returns True if one name is a substring of the other (case-insensitive).
    Handles cases like:
        org   = 'MPC Total'
        vendor = 'MPC Total Service Corp'  → True  (org in vendor)
    or the reverse:
        org   = 'MPC Total Service Corp'
        vendor = 'MPC Total'              → True  (vendor in org)
    """
    if not org_clean or not vendor_clean:
        return False
    o = org_clean.lower()
    v = vendor_clean.lower()
    return o in v or v in o


def _find_best_paid(org_clean: str, paid_map: dict[str, float]) -> float:
    """
    Looks up total paid for an org from paid_map.
    1. Exact match first.
    2. Bidirectional containment (picks entry with highest amount if multiple).
    """
    if not org_clean:
        return 0.0
    if org_clean in paid_map:
        return paid_map[org_clean]
    matches = [
        (vendor, amt)
        for vendor, amt in paid_map.items()
        if _org_matches_vendor(org_clean, vendor)
    ]
    if matches:
        return max(matches, key=lambda x: x[1])[1]
    return 0.0


def _vendor_match_cond(org_clean: str):
    """
    SQL WHERE condition for bidirectional containment (PostgreSQL).
    Matches if the cleaned Vendor_Customer column contains org_clean
    OR if org_clean contains the cleaned Vendor_Customer value.

    Example:
        org_clean = 'MPC Total'
        → matches 'MPC Total Service Corp'  (vendor ILIKE '%MPC Total%')
        → also matches 'MPC'                (org ILIKE '%MPC%')
    """
    vc = _vendor_col_cleaned()
    return and_(
        FinancialDocument.Vendor_Customer.is_not(None),
        or_(
            vc.ilike(f"%{org_clean}%"),
            literal(org_clean).ilike(func.concat("%", vc, "%")),
        ),
    )


# =============================================================================
# ENDPOINT 1 — Summary list of all subcontractors
# GET /subcontractor_metrics/
# =============================================================================

@subcontractor_metrics_bp.get("/")
def subcontractors_summary():
    """
    GET /subcontractor_metrics/?page=1&limit=25&status=Active

    Returns a paginated list of all subcontractors with:
        - basic info (name, organization, specialty, score, status)
        - active_tasks_count  : # of tasks currently assigned to their technicians
        - has_overlap         : True if any 2 active tasks overlap in dates
        - skills_count        : # of trades/skills linked to this sub
        - total_paid_usd      : total amount paid via Bill Payments (all time)
    """
    page = max(_safe_int(request.args.get("page"),  1), 1)
    limit = min(max(_safe_int(request.args.get("limit"), 25), 1), 200)
    status_filter = (request.args.get("status") or "").strip() or None
    search_q = (request.args.get("search") or "").strip() or None

    with get_session() as session:

        # ── Fetch ALL matching subs (no DB-level pagination) ────────────────
        # Pagination is applied after global sort by total_paid_usd so that
        # subs with payment data always appear before those without, across
        # all pages and not just within each page.
        subs_stmt = select(Subcontractor).order_by(
            func.coalesce(Subcontractor.Name,
                          Subcontractor.Organization, "").asc()
        )
        if status_filter:
            subs_stmt = subs_stmt.where(Subcontractor.Status == status_filter)
        if search_q:
            like = f"%{search_q}%"
            subs_stmt = subs_stmt.where(
                or_(
                    Subcontractor.Name.ilike(like),
                    Subcontractor.Organization.ilike(like),
                    Subcontractor.Specialty.ilike(like),
                )
            )
        subs = session.exec(subs_stmt).all()

        if not subs:
            return jsonify({
                "pagination": {
                    "page": page, "limit": limit,
                    "total_subs": 0, "total_pages": 1,
                },
                "subcontractors": [],
            }), 200

        sub_ids = [s.ID_Subcontractor for s in subs]

        # ── Active tasks per sub ────────────────────────────────────────────
        tasks_stmt = (
            select(
                Tasks.ID_Subcontractor,
                Tasks.ID_Tasks,
                Tasks.Designation_date,
                Tasks.Delivery_date,
            )
            .where(
                Tasks.ID_Subcontractor.in_(sub_ids),
                Tasks.Designation_date.is_not(None),
            )
        )
        tasks_by_sub: dict[str, list[dict]] = {}
        for row in session.exec(tasks_stmt).all():
            tasks_by_sub.setdefault(row.ID_Subcontractor, []).append({
                "id":            row.ID_Tasks,
                "start_date":    row.Designation_date,
                "delivery_date": row.Delivery_date,
            })

        # ── Skills count per sub ────────────────────────────────────────────
        skills_stmt = (
            select(
                SkillsSubcLink.subcon_id,
                func.count(SkillsSubcLink.skills_id).label("cnt"),
            )
            .where(SkillsSubcLink.subcon_id.in_(sub_ids))
            .group_by(SkillsSubcLink.subcon_id)
        )
        skills_count_map: dict[str, int] = {
            r.subcon_id: int(r.cnt) for r in session.exec(skills_stmt).all()
        }

        # ── Total paid (Bill Payments) per vendor ───────────────────────────
        paid_map: dict[str, float] = {}
        clean_vendor = _vendor_col_cleaned()
        paid_stmt = (
            select(
                clean_vendor.label("vendor_clean"),
                func.coalesce(
                    func.sum(FinancialTransaction.Total_Amount), 0.0
                ).label("total_paid"),
            )
            .join(
                FinancialLink,
                FinancialLink.fdocument_id == FinancialDocument.ID_FinancialDoc,
            )
            .join(
                FinancialTransaction,
                FinancialTransaction.ID_FTransaction == FinancialLink.ftransaction_id,
            )
            .where(
                FinancialDocument.Type_of_document == "Bill",
                FinancialTransaction.Type_of_transaction == "Bill Payment",
            )
            .group_by(clean_vendor)
        )
        for row in session.exec(paid_stmt).all():
            if row.vendor_clean:
                paid_map[row.vendor_clean] = _safe_float(row.total_paid)

    # ── Build full result list, then sort globally ──────────────────────────
    all_results = []
    for sub in subs:
        sub_tasks = tasks_by_sub.get(sub.ID_Subcontractor, [])
        org_clean = _clean_org(sub.Organization) or None
        all_results.append({
            "subcontractor": {
                "id":           sub.ID_Subcontractor,
                "name":         sub.Name,
                "organization": org_clean,
                "specialty":    sub.Specialty,
                "score":        sub.Score,
                "status":       sub.Status,
                "coverage_area": sub.Coverage_Area or [],
            },
            "active_tasks_count": len(sub_tasks),
            "has_overlap":        _tasks_overlap(sub_tasks),
            "skills_count":       skills_count_map.get(sub.ID_Subcontractor, 0),
            "total_paid_usd":     round(_find_best_paid(org_clean or "", paid_map), 2),
        })

    # Global sort: subs with payment data first, then alphabetically
    all_results.sort(key=lambda x: (-x["total_paid_usd"],
                                    x["subcontractor"]["name"] or ""))

    # ── Apply pagination after sort ─────────────────────────────────────────
    total_subs = len(all_results)
    total_pages = (total_subs + limit - 1) // limit if total_subs else 1
    offset = (page - 1) * limit
    page = min(page, total_pages)
    result = [
        {**item, "rank": offset + i + 1}
        for i, item in enumerate(all_results[offset: offset + limit])
    ]

    return jsonify({
        "status_filter": status_filter,
        "pagination": {
            "page":        page,
            "limit":       limit,
            "total_subs":  total_subs,
            "total_pages": total_pages,
        },
        "subcontractors": result,
    }), 200


# =============================================================================
# ENDPOINT 2 — Individual sub detail: active tasks + billing history
# GET /subcontractor_metrics/<sub_id>
# =============================================================================

@subcontractor_metrics_bp.get("/<sub_id>")
def subcontractor_detail(sub_id: str):
    """
    GET /subcontractor_metrics/<sub_id>?year=2025

    Returns full detail for one subcontractor:

    active_tasks
        tasks[]  → task_id, task_name, description, status, priority,
                   start_date (Designation_date), delivery_date,
                   technician { id, name },
                   job { job_id, type, status, project_name }
        has_overlap → True if any 2 tasks' date ranges overlap

    billing
        totals   → total_billed, total_paid, balance_pending, bill_count
        by_period → [ { year, month, month_key, label,
                        payments_count, paid_usd } ]

    year filter applies only to billing by_period.
    active_tasks always shows current/open tasks regardless of year.
    """
    year = _norm_year(request.args.get("year"))
    if request.args.get("year") is not None and year is None:
        return jsonify({"detail": "Invalid year. Use a valid number like 2025."}), 400

    with get_session() as session:

        # ── 0. Sub info ─────────────────────────────────────────────────────
        sub = session.exec(
            select(Subcontractor).where(
                Subcontractor.ID_Subcontractor == sub_id)
        ).first()
        if not sub:
            return jsonify({"detail": "Subcontractor not found."}), 404

        # ── 1. Active tasks via direct Subcontractor association ────────────
        tasks_stmt = (
            select(
                Tasks.ID_Tasks,
                Tasks.Name,
                Tasks.Task_description,
                Tasks.Task_status,
                Tasks.Priority,
                Tasks.Designation_date,
                Tasks.Delivery_date,
                Technician.ID_Technician,
                Technician.Name.label("tech_name"),
                Job.ID_Jobs,
                Job.Job_type,
                Job.Job_status,
                Job.Project_name,
            )
            .outerjoin(Technician, Technician.ID_Technician == Tasks.ID_Technician)
            .outerjoin(Job, Job.ID_Jobs == Tasks.ID_Jobs)
            .where(
                Tasks.ID_Subcontractor == sub_id,
            )
            .order_by(Tasks.Designation_date.asc().nullslast())
        )

        active_tasks = []
        for r in session.exec(tasks_stmt).all():
            active_tasks.append({
                "task_id":     r.ID_Tasks,
                "task_name":   r.Name or "—",
                "description": r.Task_description or "—",
                "status":      r.Task_status or "—",
                "priority":    r.Priority or "—",
                "start_date":  _fmt_date(r.Designation_date),
                "delivery_date": _fmt_date(r.Delivery_date),
                "technician": {
                    "id":   r.ID_Technician,
                    "name": r.tech_name or "—",
                },
                "job": {
                    "job_id":       r.ID_Jobs,
                    "type":         r.Job_type or "—",
                    "status":       (r.Job_status or "—").strip(),
                    "project_name": r.Project_name or "—",
                } if r.ID_Jobs else None,
            })

        # ── 2. Billing totals (all time) ────────────────────────────────────
        billing_totals = {
            "total_billed":    0.0,
            "total_paid":      0.0,
            "balance_pending": 0.0,
            "bill_count":      0,
        }

        if sub.Organization:
            # Bill-level totals (all time)
            bill_totals_stmt = (
                select(
                    func.count(FinancialDocument.ID_FinancialDoc).label(
                        "bill_count"),
                    func.coalesce(func.sum(FinancialDocument.Total_Amount),   0.0).label(
                        "total_billed"),
                    func.coalesce(func.sum(FinancialDocument.Balance_Amount), 0.0).label(
                        "balance_pending"),
                )
                .where(
                    FinancialDocument.Type_of_document == "Bill",
                    _vendor_match_cond(_clean_org(sub.Organization)),
                )
            )
            bt = session.exec(bill_totals_stmt).first()
            if bt:
                billing_totals["bill_count"] = int(bt.bill_count or 0)
                billing_totals["total_billed"] = round(
                    _safe_float(bt.total_billed), 2)
                billing_totals["balance_pending"] = round(
                    _safe_float(bt.balance_pending), 2)

            # Total paid via Bill Payments (Total_Amount in transaction).
            # Deduplication subquery prevents double-counting transactions
            # that are linked to more than one document.
            dedup_paid_subq = (
                select(FinancialTransaction.Total_Amount)
                .distinct()
                .add_columns(FinancialTransaction.ID_FTransaction)
                .select_from(FinancialLink)
                .join(
                    FinancialDocument,
                    FinancialDocument.ID_FinancialDoc == FinancialLink.fdocument_id,
                )
                .join(
                    FinancialTransaction,
                    FinancialTransaction.ID_FTransaction == FinancialLink.ftransaction_id,
                )
                .where(
                    FinancialDocument.Type_of_document == "Bill",
                    FinancialTransaction.Type_of_transaction == "Bill Payment",
                    _vendor_match_cond(_clean_org(sub.Organization)),
                )
                .subquery()
            )
            paid_total_stmt = select(
                func.coalesce(func.sum(dedup_paid_subq.c.Total_Amount), 0.0).label("total_paid")
            )
            pt = session.exec(paid_total_stmt).first()
            billing_totals["total_paid"] = round(
                _safe_float(pt if pt is not None else 0.0), 2)

        # ── 3. Billing by period (year/month of Date_of_payment) ────────────
        by_period = []

        if sub.Organization:
            # Deduplication subquery: one row per unique transaction
            vendor_filter = _vendor_match_cond(_clean_org(sub.Organization))
            dedup_subq = (
                select(
                    FinancialTransaction.ID_FTransaction,
                    FinancialTransaction.Date_of_payment,
                    FinancialTransaction.Total_Amount,
                )
                .distinct()
                .select_from(FinancialLink)
                .join(
                    FinancialDocument,
                    FinancialDocument.ID_FinancialDoc == FinancialLink.fdocument_id,
                )
                .join(
                    FinancialTransaction,
                    FinancialTransaction.ID_FTransaction == FinancialLink.ftransaction_id,
                )
                .where(
                    FinancialDocument.Type_of_document == "Bill",
                    FinancialTransaction.Type_of_transaction == "Bill Payment",
                    vendor_filter,
                    FinancialTransaction.Date_of_payment.is_not(None),
                )
            )
            if year is not None:
                dedup_subq = dedup_subq.where(
                    extract("year", FinancialTransaction.Date_of_payment) == year
                )
            dedup_subq = dedup_subq.subquery()

            year_col  = extract("year",  dedup_subq.c.Date_of_payment)
            month_col = extract("month", dedup_subq.c.Date_of_payment)
            month_key = func.to_char(dedup_subq.c.Date_of_payment, "YYYY-MM")
            month_lbl = func.to_char(dedup_subq.c.Date_of_payment, "Month YYYY")

            period_stmt = (
                select(
                    year_col.label("year"),
                    month_col.label("month"),
                    month_key.label("month_key"),
                    month_lbl.label("label"),
                    func.count(dedup_subq.c.ID_FTransaction).label("payments_count"),
                    func.coalesce(func.sum(dedup_subq.c.Total_Amount), 0.0).label("paid_usd"),
                )
                .group_by(year_col, month_col, month_key, month_lbl)
                .order_by(year_col.desc(), month_col.desc())
            )

            for row in session.exec(period_stmt).all():
                by_period.append({
                    "year":           int(row.year or 0),
                    "month":          int(row.month or 0),
                    "month_key":      row.month_key or "—",
                    "label":          (row.label or "—").strip(),
                    "payments_count": int(row.payments_count or 0),
                    "paid_usd":       round(_safe_float(row.paid_usd), 2),
                })

        # ── 4. Pending bills (Percentage_Paid < 100 o NULL) ─────────────────
        pending_bills = []

        if sub.Organization:
            pending_stmt = (
                select(
                    FinancialDocument.ID_FinancialDoc,
                    FinancialDocument.Vendor_Customer,
                    FinancialDocument.Total_Amount,
                    FinancialDocument.Balance_Amount,
                    FinancialDocument.Percentage_Paid,
                    FinancialDocument.Due_Date,
                    FinancialDocument.Notes,
                    FinancialDocument.ID_Order,
                    Order.Title.label("order_title"),
                    Order.Formula.label("order_formula"),
                    Order.Adj_formula.label("order_adj_formula"),
                )
                .outerjoin(Order, Order.ID_Order == FinancialDocument.ID_Order)
                .where(
                    FinancialDocument.Type_of_document == "Bill",
                    or_(
                        FinancialDocument.Percentage_Paid < 100,
                        FinancialDocument.Percentage_Paid.is_(None),
                    ),
                    _vendor_match_cond(_clean_org(sub.Organization)),
                )
                .order_by(FinancialDocument.Due_Date.asc().nullslast())
            )
            for r in session.exec(pending_stmt).all():
                pending_bills.append({
                    "bill_id":         r.ID_FinancialDoc,
                    "vendor_customer": _clean_org(r.Vendor_Customer or ""),
                    "total_amount":    round(_safe_float(r.Total_Amount), 2),
                    "balance_amount":  round(_safe_float(r.Balance_Amount), 2),
                    "percentage_paid": r.Percentage_Paid,
                    "due_date":        _fmt_date(r.Due_Date),
                    "notes":           r.Notes or None,
                    "order": {
                        "order_id":    r.ID_Order,
                        "title":       r.order_title or "—",
                        "formula":     r.order_formula,
                        "adj_formula": r.order_adj_formula,
                    } if r.ID_Order else None,
                })

    return jsonify({
        "subcontractor": {
            "id":            sub.ID_Subcontractor,
            "name":          sub.Name,
            "organization":  _clean_org(sub.Organization) or None,
            "specialty":     sub.Specialty,
            "score":         sub.Score,
            "status":        sub.Status,
            "email":         sub.Email_Address,
            "phone":         sub.Phone_Number,
            "coverage_area": sub.Coverage_Area or [],
        },
        "year_filter": year,
        "active_tasks": {
            "count":       len(active_tasks),
            "has_overlap": _tasks_overlap(active_tasks),
            "tasks":       active_tasks,
        },
        "billing": {
            "totals":    billing_totals,
            "by_period": by_period,
        },
        "pending_bills": {
            "count": len(pending_bills),
            "bills": pending_bills,
        },
    }), 200


# =============================================================================
# ENDPOINT 3 — Directory: subcontractors grouped by trade/skill
# GET /subcontractor_metrics/by-trade
# =============================================================================

@subcontractor_metrics_bp.get("/by-trade")
def subcontractors_by_trade():
    """
    GET /subcontractor_metrics/by-trade?trade=Electrical

    Groups subcontractors by Division_trade (from Skills).
    Optional ?trade= filter to get only subs for a specific trade.

    Response structure:
        trades[] → {
            division_trade, skill_id, skill_name, total_subs,
            subcontractors[] → { id, name, organization, status, score, certificated }
        }
    """
    trade_filter = (request.args.get("trade") or "").strip() or None

    with get_session() as session:
        stmt = (
            select(
                Skills.ID_Skill,
                Skills.Skill_name,
                Skills.Division_trade,
                Subcontractor.ID_Subcontractor,
                Subcontractor.Name,
                Subcontractor.Organization,
                Subcontractor.Status,
                Subcontractor.Score,
                SkillsSubcLink.Certificated,
            )
            .join(SkillsSubcLink, SkillsSubcLink.skills_id == Skills.ID_Skill)
            .join(
                Subcontractor,
                Subcontractor.ID_Subcontractor == SkillsSubcLink.subcon_id,
            )
            .order_by(
                func.coalesce(Skills.Division_trade, "").asc(),
                func.coalesce(Skills.Skill_name, "").asc(),
                func.coalesce(Subcontractor.Name,
                              Subcontractor.Organization, "").asc(),
            )
        )

        if trade_filter:
            stmt = stmt.where(Skills.Division_trade.ilike(f"%{trade_filter}%"))

        rows = session.exec(stmt).all()

    # ── Group by (Division_trade + Skill) ───────────────────────────────────
    # Key: (division_trade, skill_id)
    trade_map: dict[tuple, dict] = {}
    for r in rows:
        key = (r.Division_trade or "Unknown", r.ID_Skill)
        if key not in trade_map:
            trade_map[key] = {
                "division_trade":  r.Division_trade or "Unknown",
                "skill_id":        r.ID_Skill,
                "skill_name":      r.Skill_name or "—",
                "total_subs":      0,
                "subcontractors":  [],
            }
        trade_map[key]["total_subs"] += 1
        trade_map[key]["subcontractors"].append({
            "id":            r.ID_Subcontractor,
            "name":          r.Name,
            "organization":  r.Organization,
            "status":        r.Status,
            "score":         r.Score,
            "certificated":  r.Certificated,
        })

    trades = sorted(
        trade_map.values(),
        key=lambda t: (t["division_trade"], t["skill_name"]),
    )

    return jsonify({
        "trade_filter": trade_filter,
        "total_trades": len(trades),
        "trades":       trades,
    }), 200
