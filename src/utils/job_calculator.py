# =============================================================================
# src/utils/job_calculator.py
# =============================================================================

from __future__ import annotations

from typing import Optional
from sqlmodel import Session, select

from ..models.JobModel import Job
from ..models.OrderModel import Order
from ..models.ChangeOrderModel import ChangeOrder
from ..models.EstimateCostModel import EstimateCost
from ..models.PurchaseModel import Purchase
from ..models.MultiplierRModel import MultiplierR
from ..models.link_models.JobMultiplierR import JobMultiplierRLink

BDF_SLOTS = 3   # Podio supports exactly 3 Bldg_dept_fees slots

DEFAULT_MULTIPLIER_RANGES = [
    (0,      27_000, 1.027),
    (27_000, 63_000, 1.023),
]
DEFAULT_MULTIPLIER_FALLBACK = 1.018


def _resolve_multiplier(formula_value: float, job: Job, session: Session) -> float:

    multipliers: list[MultiplierR] = list(
        session.exec(
            select(MultiplierR)
            .join(JobMultiplierRLink, MultiplierR.ID_MultiplierR == JobMultiplierRLink.multiplier_id)
            .where(JobMultiplierRLink.job_id == job.ID_Jobs)
        ).all()
    )

    # Si hay un multiplicador vinculado que cubre el rango → úsalo
    for m in multipliers:
        start = float(m.Start_value) if m.Start_value is not None else 0.0
        end   = float(m.End_value)   if m.End_value   is not None else float("inf")
        if start <= formula_value <= end:
            return float(m.Multiplier) if m.Multiplier is not None else DEFAULT_MULTIPLIER_FALLBACK

    # Si no hay ninguno vinculado → rangos default (incluye el 1.018 como fallback final)
    for start, end, factor in DEFAULT_MULTIPLIER_RANGES:
        if start <= formula_value <= end:
            return factor

    return DEFAULT_MULTIPLIER_FALLBACK


def _resolve_job_id_from_change_order(co: ChangeOrder, session: Session) -> Optional[str]:
    if co.ID_Jobs:
        return co.ID_Jobs

    if co.ID_Order:
        order = session.exec(
            select(Order).where(Order.ID_Order == co.ID_Order)
        ).first()
        if not order:
            return None

        if order.job_podio_id:
            linked_job = session.exec(
                select(Job).where(Job.podio_item_id == order.job_podio_id)
            ).first()
            if linked_job:
                return linked_job.ID_Jobs

        ec = session.exec(
            select(EstimateCost).where(
                EstimateCost.ID_Order == co.ID_Order,
                EstimateCost.ID_Jobs.is_not(None),
            )
        ).first()
        if ec and ec.ID_Jobs:
            return ec.ID_Jobs

    return None


def _build_bdf_array(bdf_costs: list[EstimateCost]) -> list[Optional[float]]:
    """
    Builds a compact 3-slot array for Bldg_dept_fees.

    Strategy: values are packed left-to-right ordered by ID_EstimateCost
    (a stable proxy for creation order). Unused slots are None.

    Examples:
      3 BDF costs (val=20, 30, 50) → [20.0, 30.0, 50.0]
      2 BDF costs (val=20, 50)     → [20.0, 50.0, None]   ← after deleting the 30
      1 BDF cost  (val=20)         → [20.0, None,  None]
      0 BDF costs                  → [None, None,  None]

    Since the 3 Podio slots have no semantic meaning (they are generic fee fields),
    there is no need to track which cost maps to which slot. Compacting guarantees
    Podio always receives a valid left-aligned array regardless of which costs
    were added or removed.
    """
    # Sort by ID_EstimateCost for a stable, deterministic order
    sorted_costs = sorted(bdf_costs, key=lambda ec: ec.ID_EstimateCost or "")

    result: list[Optional[float]] = [None, None, None]
    for i, ec in enumerate(sorted_costs[:BDF_SLOTS]):
        result[i] = float(ec.Builder_cost) if ec.Builder_cost is not None else 0.0

    return result


def recalculate_job_fields(job_id: str, session: Session) -> dict:
    job = session.exec(select(Job).where(Job.ID_Jobs == job_id)).first()
    if not job:
        return {}

    # ── 1. EstimateCosts ─────────────────────────────────────────────────────
    estimate_costs = session.exec(
        select(EstimateCost).where(EstimateCost.ID_Jobs == job_id)
    ).all()

    estimated_rent     = 0.0
    estimated_material = 0.0
    estimated_city     = 0.0
    ptl_gc_fee_num     = 0.0
    bdf_costs: list[EstimateCost] = []

    for ec in estimate_costs:
        cost = float(ec.Builder_cost or 0)
        ct   = (ec.Cost_type or "").strip()

        if ct == "Rent":
            estimated_rent += cost
        elif ct == "Material":
            estimated_material += cost
        elif ct == "Permit":
            estimated_city += cost
        elif ct == "PTLGCF":
            ptl_gc_fee_num += cost
        elif ct == "BDF":
            bdf_costs.append(ec)

    # Compact 3-slot array — nulls at the end for unused slots
    bldg_dept_fees_list = _build_bdf_array(bdf_costs)

    # Gqm_paid_fees = sum of non-null BDF values
    gqm_paid_fees = sum(v for v in bldg_dept_fees_list if v is not None)

    # ── 2. Purchases ─────────────────────────────────────────────────────────
    purchases = session.exec(
        select(Purchase).where(Purchase.ID_Jobs == job_id)
    ).all()
    gqm_total_materials_fees = sum(float(p.Total_spending or 0) for p in purchases)

    # ── 3. Orders → Adj_formula ──────────────────────────────────────────────
    counted_order_ids: set[str] = set()
    orders_adj: list[float] = []

    if job.podio_item_id:
        podio_orders = session.exec(
            select(Order).where(Order.job_podio_id == job.podio_item_id)
        ).all()
        for o in podio_orders:
            if o.ID_Order:
                counted_order_ids.add(o.ID_Order)
            orders_adj.append(float(o.Adj_formula or 0))

    ec_order_ids = {
        ec.ID_Order for ec in estimate_costs if ec.ID_Order is not None
    }
    for order_id in ec_order_ids:
        if order_id in counted_order_ids:
            continue
        order = session.exec(
            select(Order).where(Order.ID_Order == order_id)
        ).first()
        if order:
            counted_order_ids.add(order_id)
            orders_adj.append(float(order.Adj_formula or 0))

    sum_adj_formula = sum(orders_adj)

    # ── 4. ChangeOrders generales ────────────────────────────────────────────
    change_orders_job = session.exec(
        select(ChangeOrder).where(
            ChangeOrder.ID_Jobs == job_id,
            ChangeOrder.ID_Order == None,  # noqa: E711
        )
    ).all()
    gqm_total_change_orders = sum(
        float(co.ChangeOrderFormula or 0) for co in change_orders_job
    )

    # ── 5. Manual inputs ─────────────────────────────────────────────────────
    gqm_target_sold_pricing = float(job.Gqm_target_sold_pricing or 0)

    # ── 6. Calculations ──────────────────────────────────────────────────────

    calc_estimated_rent           = estimated_rent
    calc_estimated_material       = estimated_material
    calc_estimated_city           = estimated_city
    calc_ptl_gc_fee               = ptl_gc_fee_num
    calc_bldg_dept_fees           = bldg_dept_fees_list   # [float|None, float|None, float|None]
    calc_gqm_paid_fees            = gqm_paid_fees
    calc_gqm_total_materials_fees = gqm_total_materials_fees

    calc_tech_formula_pricing = sum_adj_formula
    calc_gqm_formula_pricing  = (
        sum_adj_formula
        + calc_estimated_material
        + calc_estimated_rent
        + calc_estimated_city
    )

    calc_gqm_adj_formula_pricing = (
        calc_gqm_formula_pricing
        * _resolve_multiplier(calc_gqm_formula_pricing, job, session)
    )

    calc_gqm_final_sold_pricing = (
        gqm_target_sold_pricing
        + gqm_total_change_orders
        + calc_ptl_gc_fee
    )
    calc_acc_receivable = calc_gqm_final_sold_pricing

    calc_gqm_premium_in_money = (
        calc_gqm_final_sold_pricing - calc_gqm_adj_formula_pricing
    )
    calc_gqm_target_return = (
        (calc_gqm_final_sold_pricing - calc_gqm_adj_formula_pricing)
        / calc_gqm_final_sold_pricing
        if calc_gqm_final_sold_pricing != 0
        else 0.0
    )

    calc_gqm_final_form_pricing = (
        sum_adj_formula
        + calc_gqm_total_materials_fees
        + calc_gqm_paid_fees
    )
    calc_gqm_final_adj_form_pricing = calc_gqm_final_form_pricing * 1.027

    calc_gqm_final_percentage = (
        (calc_acc_receivable - calc_gqm_final_adj_form_pricing)
        / calc_acc_receivable
        if calc_acc_receivable != 0
        else 0.0
    )
    calc_gqm_final_target_return = calc_gqm_final_percentage
    calc_gqm_final_prem_in_money = (
        calc_gqm_final_sold_pricing - calc_gqm_final_adj_form_pricing
    )

    return {
        "Estimated_rent":             calc_estimated_rent,
        "Estimated_material":         calc_estimated_material,
        "Estimated_city":             calc_estimated_city,
        "Ptl_gc_fee":                 calc_ptl_gc_fee,
        "Bldg_dept_fees":             calc_bldg_dept_fees,
        "Gqm_paid_fees":              calc_gqm_paid_fees,
        "Gqm_total_materials_fees":   calc_gqm_total_materials_fees,
        "Tech_formula_pricing":       calc_tech_formula_pricing,
        "Gqm_formula_pricing":        calc_gqm_formula_pricing,
        "Gqm_adj_formula_pricing":    calc_gqm_adj_formula_pricing,
        "Gqm_total_change_orders":    gqm_total_change_orders,
        "Gqm_final_sold_pricing":     calc_gqm_final_sold_pricing,
        "Acc_receivable":             calc_acc_receivable,
        "Gqm_premium_in_money":       calc_gqm_premium_in_money,
        "Gqm_target_return":          calc_gqm_target_return,
        "Gqm_final_form_pricing":     calc_gqm_final_form_pricing,
        "Gqm_final_adj_form_pricing": calc_gqm_final_adj_form_pricing,
        "Gqm_final_percentage":       calc_gqm_final_percentage,
        "Gqm_final_target_return":    calc_gqm_final_target_return,
        "Gqm_final_prem_in_money":    calc_gqm_final_prem_in_money,
    }


def recalculate_and_apply(job_id: str, session: Session) -> Optional[Job]:
    calculated = recalculate_job_fields(job_id, session)
    if not calculated:
        return None

    job = session.exec(select(Job).where(Job.ID_Jobs == job_id)).first()
    if not job:
        return None

    for field, value in calculated.items():
        setattr(job, field, value)

    session.add(job)
    return job


def recalculate_and_apply_from_change_order(
    change_order: ChangeOrder, session: Session
) -> Optional[Job]:
    job_id = _resolve_job_id_from_change_order(change_order, session)
    if not job_id:
        return None
    return recalculate_and_apply(job_id, session)


def recalculate_order_formulas(order_id: str, session: Session):
    order = session.exec(select(Order).where(Order.ID_Order == order_id)).first()
    if not order: return
    # 1. Sumar todos los Builder_Cost de los Estimate Costs asociados a esta order
    costs = session.exec(select(EstimateCost).where(EstimateCost.ID_Order == order_id)).all()
    total_formula = sum([float(c.Builder_cost or 0) for c in costs])
    
    # 2. Sumar todos los ChangeOrder previstos para esta order
    change_orders = session.exec(select(ChangeOrder).where(ChangeOrder.ID_Order == order_id)).all()
    co_sum = sum([float(co.ChangeOrderFormula or 0) for co in change_orders])
    
    # 3. Asignar correctamante
    order.Formula = total_formula
    order.Adj_formula = total_formula + co_sum
    session.add(order)
