# src/services/metrics/timeline_metrics_service.py
from __future__ import annotations

from datetime import datetime, timedelta, date
from collections import defaultdict

from sqlmodel import select
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from ...database.db_sqlmodel import get_session
from ...models.TLActivityModel import TLActivity
from ...models.JobModel import Job
from ...models.MemberModel import Member

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PERIODS = ("day", "week", "month")

ACTION_CATEGORIES = {
    "created":       ["job created", "order created", "task created",
                      "change order created", "estimate cost created",
                      "subcontractor linked", "member linked"],
    "updated":       ["job updated", "order updated", "task updated",
                      "change order updated", "estimate cost updated"],
    "deleted":       ["job deleted", "order deleted", "task deleted",
                      "change order deleted", "estimate cost deleted",
                      "subcontractor unlinked", "member unlinked"],
    "synced_podio":  ["podio", "synced"],
    "status_change": ["status"],
}


def _categorize(action: str | None) -> str:
    if not action:
        return "other"
    a = action.lower()
    for cat, keywords in ACTION_CATEGORIES.items():
        if any(k in a for k in keywords):
            return cat
    return "other"


# ---------------------------------------------------------------------------
# Date range helpers
# ---------------------------------------------------------------------------

def _parse_period_dates(
    period: str,
    ref_date_str: str | None,
) -> tuple[datetime, datetime]:
    """
    Returns (start_dt, end_dt) for the requested period.
    ref_date_str: ISO date string (YYYY-MM-DD). Defaults to today.
    """
    try:
        ref = date.fromisoformat(ref_date_str) if ref_date_str else date.today()
    except (ValueError, TypeError):
        ref = date.today()

    if period == "day":
        start = datetime(ref.year, ref.month, ref.day, 0,  0,  0)
        end   = datetime(ref.year, ref.month, ref.day, 23, 59, 59)

    elif period == "week":
        # Monday of the week containing ref
        monday = ref - timedelta(days=ref.weekday())
        sunday = monday + timedelta(days=6)
        start  = datetime(monday.year, monday.month, monday.day, 0,  0,  0)
        end    = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59)

    elif period == "month":
        import calendar
        last_day = calendar.monthrange(ref.year, ref.month)[1]
        start = datetime(ref.year, ref.month, 1,        0,  0,  0)
        end   = datetime(ref.year, ref.month, last_day, 23, 59, 59)

    else:
        # fallback: current month
        import calendar
        today    = date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        start    = datetime(today.year, today.month, 1,        0,  0,  0)
        end      = datetime(today.year, today.month, last_day, 23, 59, 59)

    return start, end


def _day_label(dt: datetime, period: str) -> str:
    if period == "month":
        return dt.strftime("%b %d")
    if period == "week":
        return dt.strftime("%a %d")
    return dt.strftime("%H:00")


# ---------------------------------------------------------------------------
# Core query
# ---------------------------------------------------------------------------

def get_timeline_metrics_data(
    job_id: str,
    period: str = "month",
    ref_date: str | None = None,
) -> tuple[dict | None, tuple[str, int] | None]:
    """
    Returns (data_dict, None) on success or (None, (error_message, status_code)) on failure.
    """
    period = period.lower() if period else "month"
    if period not in VALID_PERIODS:
        return None, (f"Invalid period '{period}'. Use: {', '.join(VALID_PERIODS)}", 400)

    try:
        with get_session() as session:

            # ── Verify job exists ──────────────────────────────────────────
            job = session.exec(
                select(Job).where(Job.ID_Jobs == job_id)
            ).first()
            if not job:
                return None, (f"Job '{job_id}' not found", 404)

            start_dt, end_dt = _parse_period_dates(period, ref_date)

            # ── Fetch activities in range ──────────────────────────────────
            statement = (
                select(TLActivity)
                .options(joinedload(TLActivity.member))
                .where(TLActivity.ID_Jobs == job_id)
                .where(TLActivity.Action_datetime >= start_dt)
                .where(TLActivity.Action_datetime <= end_dt)
                .order_by(TLActivity.Action_datetime.asc())
            )
            entries: list[TLActivity] = session.exec(statement).unique().all()

            # ── Summary counters by category ───────────────────────────────
            category_counts: dict[str, int] = defaultdict(int)
            source_counts:   dict[str, int] = defaultdict(int)
            member_counts:   dict[str, dict] = {}   # member_id -> {name, count}

            for e in entries:
                cat = _categorize(e.Action)
                category_counts[cat] += 1

                # source
                desc = e.Description or ""
                if "Source: Podio" in desc:
                    source_counts["podio"] += 1
                else:
                    source_counts["app"] += 1

                # member activity
                if e.ID_Member:
                    if e.ID_Member not in member_counts:
                        name = None
                        if e.member:
                            name = getattr(e.member, "Member_Name", None) or getattr(e.member, "name", None)
                        member_counts[e.ID_Member] = {
                            "member_id": e.ID_Member,
                            "name":      name or e.ID_Member,
                            "count":     0,
                        }
                    member_counts[e.ID_Member]["count"] += 1

            # ── Activity-by-day/hour buckets ───────────────────────────────
            if period == "day":
                # Bucket by hour
                buckets: dict[str, int] = {f"{h:02d}:00": 0 for h in range(24)}
                for e in entries:
                    if e.Action_datetime:
                        key = e.Action_datetime.strftime("%H:00")
                        buckets[key] = buckets.get(key, 0) + 1
                activity_over_time = [{"label": k, "count": v} for k, v in sorted(buckets.items())]

            elif period == "week":
                from datetime import timedelta
                monday = start_dt.date()
                buckets = {}
                for i in range(7):
                    d = monday + timedelta(days=i)
                    buckets[d.strftime("%a %d")] = 0
                for e in entries:
                    if e.Action_datetime:
                        key = e.Action_datetime.strftime("%a %d")
                        if key in buckets:
                            buckets[key] += 1
                activity_over_time = [{"label": k, "count": v} for k, v in buckets.items()]

            else:  # month
                import calendar
                last_day = calendar.monthrange(start_dt.year, start_dt.month)[1]
                buckets = {f"{start_dt.strftime('%b')} {d:02d}": 0 for d in range(1, last_day + 1)}
                for e in entries:
                    if e.Action_datetime:
                        key = e.Action_datetime.strftime("%b %d")
                        if key in buckets:
                            buckets[key] += 1
                activity_over_time = [{"label": k, "count": v} for k, v in buckets.items()]

            # ── Serialized timeline entries ────────────────────────────────
            timeline_entries = []
            for e in entries:
                member_name = None
                if e.member:
                    member_name = getattr(e.member, "Member_Name", None) or getattr(e.member, "name", None)

                desc = e.Description or ""
                source = "Podio" if "Source: Podio" in desc else "App"
                body   = "  |  ".join(
                    p for p in desc.split("  |  ")
                    if not p.startswith("Source:")
                ) or None

                timeline_entries.append({
                    "id":          e.ID_TLActivity,
                    "action":      e.Action,
                    "datetime":    e.Action_datetime.isoformat() if e.Action_datetime else None,
                    "description": body,
                    "source":      source,
                    "member_id":   e.ID_Member,
                    "member_name": member_name,
                })

            # ── Build response dict ────────────────────────────────────────
            data = {
                "job_id":       job_id,
                "job_type":     job.Job_type,
                "period":       period,
                "ref_date":     ref_date or date.today().isoformat(),
                "date_range": {
                    "start": start_dt.isoformat(),
                    "end":   end_dt.isoformat(),
                },
                "summary": {
                    "total_events":  len(entries),
                    "by_category":   dict(category_counts),
                    "by_source":     dict(source_counts),
                    "active_members": sorted(
                        member_counts.values(),
                        key=lambda x: x["count"],
                        reverse=True
                    ),
                },
                "activity_over_time": activity_over_time,
                "timeline":           timeline_entries,
            }

            return data, None

    except SQLAlchemyError as e:
        return None, (f"Database error: {e}", 500)
    except Exception as e:
        return None, (f"Unexpected error: {e}", 500)