"""
Migration: Unify Permit and BDF estimate cost types into a single BDF type with status.

What this does:
  1. Existing Permit costs → Cost_type='BDF', Status='Estimated'
     (they were quoted estimates → now represented as BDF Estimated)
  2. Existing BDF costs with no status → Status='Approved'
     (they were confirmed Bldg_dept_fees entries → now represented as BDF Approved)

After running this script, call recalculate_and_apply() for each affected job
to refresh all calculated fields (Estimated_city, Bldg_dept_fees, Gqm_paid_fees, etc.).

Usage:
    cd gqm-api
    python -m migrations.migrate_bdf_status
"""

import sys
import os

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, select
from src.database.db_sqlmodel import engine
from src.models.EstimateCostModel import EstimateCost
from src.utils.job_calculator import recalculate_and_apply


def run_migration(dry_run: bool = False) -> None:
    with Session(engine) as session:

        # ── 1. Permit → BDF Estimated ────────────────────────────────────────
        permit_costs = session.exec(
            select(EstimateCost).where(EstimateCost.Cost_type == "Permit")
        ).all()

        print(f"[Permit → BDF Estimated] Found {len(permit_costs)} cost(s)")
        affected_job_ids: set[str] = set()

        for ec in permit_costs:
            print(f"  - {ec.ID_EstimateCost}: '{ec.Title}' (Job: {ec.ID_Jobs}, amount: {ec.Builder_cost})")
            if not dry_run:
                ec.Cost_type = "BDF"
                ec.Status = "Estimated"
                session.add(ec)
            if ec.ID_Jobs:
                affected_job_ids.add(ec.ID_Jobs)

        # ── 2. BDF (no status) → BDF Approved ───────────────────────────────
        bdf_costs = session.exec(
            select(EstimateCost).where(
                EstimateCost.Cost_type == "BDF",
                (EstimateCost.Status == None) | (EstimateCost.Status == ""),  # noqa: E711
            )
        ).all()

        print(f"\n[BDF → BDF Approved] Found {len(bdf_costs)} cost(s)")

        for ec in bdf_costs:
            print(f"  - {ec.ID_EstimateCost}: '{ec.Title}' (Job: {ec.ID_Jobs}, builder={ec.Builder_cost}, client={ec.Client_price})")
            if not dry_run:
                ec.Status = "Approved"
                # Client_price holds the confirmed amount. If it was never set, seed it
                # from Builder_cost so _build_bdf_array produces the correct Bldg_dept_fees.
                if ec.Client_price is None:
                    ec.Client_price = ec.Builder_cost
                session.add(ec)
            if ec.ID_Jobs:
                affected_job_ids.add(ec.ID_Jobs)

        if dry_run:
            print("\n[DRY RUN] No changes committed.")
            return

        session.commit()
        print(f"\n[Migration] Committed. Recalculating {len(affected_job_ids)} job(s)…")

        # ── 3. Recalculate all affected jobs ─────────────────────────────────
        for job_id in affected_job_ids:
            try:
                recalculate_and_apply(job_id, session)
                session.commit()
                print(f"  ✓ Recalculated job {job_id}")
            except Exception as e:
                print(f"  ✗ Failed to recalculate job {job_id}: {e}")

        print("\n[Migration] Done.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN — no changes will be written ===\n")
    run_migration(dry_run=dry)
