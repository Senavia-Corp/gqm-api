# =============================================================================
# src/utils/job_calculator.py
#
# Servicio de cálculo automático de campos derivados del Job.
#
# Principio: esta función es PURA en cuanto a lógica — solo calcula y retorna
# un dict con los campos actualizados. No hace commit ni side effects.
# El llamador es responsable de aplicar los valores y guardar.
#
# Puntos de disparo (dónde se llama recalculate_and_apply):
#   1. job_routes.py        → update_job()        (PATCH /jobs/<id>)
#   2. order_routes.py      → create/update/delete order
#   3. purchase_routes.py   → create/update/delete purchase
#   4. estimate_routes.py   → create/update/delete estimate cost
#   5. webhook.py           → podio_jobs_webhook() (item.create / item.update)
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


# ---------------------------------------------------------------------------
# Multiplicadores por defecto (cuando el Job no tiene ninguno asociado
# o cuando Job_type == "PTL")
# ---------------------------------------------------------------------------
DEFAULT_MULTIPLIER_RANGES = [
    (0,      27_000, 1.027),
    (27_000, 63_000, 1.023),
]
DEFAULT_MULTIPLIER_FALLBACK = 1.018   # > 63 000 o PTL


def _resolve_multiplier(formula_value: float, job: Job, session: Session) -> float:
    """
    Devuelve el multiplicador aplicable para Gqm_adj_formula_pricing.

    Orden de prioridad:
      1. Si Job_type == "PTL"  → siempre 1.018
      2. Si el Job tiene multipliers asociados que cubran formula_value → usa ese
      3. Fallback a rangos por defecto
    """
    if job.Job_type and job.Job_type.upper() == "PTL":
        return DEFAULT_MULTIPLIER_FALLBACK

    # Cargar multipliers asociados al Job via tabla intermedia
    multipliers: list[MultiplierR] = list(
        session.exec(
            select(MultiplierR)
            .join(JobMultiplierRLink, MultiplierR.ID_MultiplierR == JobMultiplierRLink.multiplier_id)
            .where(JobMultiplierRLink.job_id == job.ID_Jobs)
        ).all()
    )

    for m in multipliers:
        start = float(m.Start_value) if m.Start_value is not None else 0.0
        end   = float(m.End_value)   if m.End_value   is not None else float("inf")
        if start <= formula_value <= end:
            return float(m.Multiplier) if m.Multiplier is not None else DEFAULT_MULTIPLIER_FALLBACK

    # Sin multiplier asociado que cubra el valor → rangos por defecto
    for start, end, factor in DEFAULT_MULTIPLIER_RANGES:
        if start <= formula_value <= end:
            return factor

    return DEFAULT_MULTIPLIER_FALLBACK


def recalculate_job_fields(job_id: str, session: Session) -> dict:
    """
    Calcula todos los campos derivados del Job identificado por job_id.

    Retorna un dict { campo_python: valor_calculado } con TODOS los campos
    que deben actualizarse. El llamador debe aplicar los valores al objeto Job
    y hacer save/commit.

    Si job_id no existe, retorna {}.
    """
    job = session.exec(select(Job).where(Job.ID_Jobs == job_id)).first()
    if not job:
        return {}

    # -------------------------------------------------------------------------
    # 1. EstimateCosts agrupados por Cost_type
    # -------------------------------------------------------------------------
    estimate_costs = session.exec(
        select(EstimateCost).where(EstimateCost.ID_Jobs == job_id)
    ).all()

    estimated_rent     = 0.0
    estimated_material = 0.0
    estimated_city     = 0.0
    ptl_gc_fee_num     = 0.0
    bldg_dept_fees_list: list[str] = []

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
            # Cada BDF es un elemento string del array Bldg_dept_fees
            bldg_dept_fees_list.append(
                str(ec.Builder_cost) if ec.Builder_cost is not None else "0"
            )

    # Gqm_paid_fees = suma de los strings de Bldg_dept_fees casteados a float
    gqm_paid_fees = sum(float(v) for v in bldg_dept_fees_list if v)

    # -------------------------------------------------------------------------
    # 2. Purchases → Gqm_total_materials_fees
    # -------------------------------------------------------------------------
    purchases = session.exec(
        select(Purchase).where(Purchase.ID_Jobs == job_id)
    ).all()
    gqm_total_materials_fees = sum(float(p.Total_spending or 0) for p in purchases)

    # -------------------------------------------------------------------------
    # 3. Orders → suma de Adj_formula
    #    Vinculación dual: por job_podio_id (Podio) y por EstimateCost.ID_Order (DB)
    # -------------------------------------------------------------------------
    counted_order_ids: set[str] = set()
    orders_adj: list[float] = []

    # Vía podio_item_id
    if job.podio_item_id:
        podio_orders = session.exec(
            select(Order).where(Order.job_podio_id == job.podio_item_id)
        ).all()
        for o in podio_orders:
            if o.ID_Order:
                counted_order_ids.add(o.ID_Order)
            orders_adj.append(float(o.Adj_formula or 0))

    # Vía EstimateCosts → ID_Order (evita doble conteo)
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

    # -------------------------------------------------------------------------
    # 4. ChangeOrders vinculadas al Job sin Order específica
    # -------------------------------------------------------------------------
    change_orders_job = session.exec(
        select(ChangeOrder).where(
            ChangeOrder.ID_Jobs == job_id,
            ChangeOrder.ID_Order == None,  # noqa: E711
        )
    ).all()
    gqm_total_change_orders = sum(
        float(co.ChangeOrderFormula or 0) for co in change_orders_job
    )

    # -------------------------------------------------------------------------
    # 5. Campos manuales del Job que son inputs del usuario (no se recalculan)
    # -------------------------------------------------------------------------
    gqm_target_sold_pricing = float(job.Gqm_target_sold_pricing or 0)

    # -------------------------------------------------------------------------
    # 6. Cálculo en orden de dependencias
    # -------------------------------------------------------------------------

    # Nivel 1 — directos desde EstimateCosts y Purchases
    calc_estimated_rent           = estimated_rent
    calc_estimated_material       = estimated_material
    calc_estimated_city           = estimated_city
    calc_ptl_gc_fee               = ptl_gc_fee_num       # float para fórmulas
    calc_bldg_dept_fees           = bldg_dept_fees_list  # list[str] para el campo JSON
    calc_gqm_paid_fees            = gqm_paid_fees
    calc_gqm_total_materials_fees = gqm_total_materials_fees

    # Nivel 2 — Orders + EstimateCosts
    calc_tech_formula_pricing = sum_adj_formula
    calc_gqm_formula_pricing  = (
        sum_adj_formula
        + calc_estimated_material
        + calc_estimated_rent
        + calc_estimated_city
    )

    # Nivel 3 — multiplier
    calc_gqm_adj_formula_pricing = (
        calc_gqm_formula_pricing
        * _resolve_multiplier(calc_gqm_formula_pricing, job, session)
    )

    # Nivel 4 — ChangeOrders + Ptl_gc_fee + input manual
    # Gqm_final_sold_pricing y Acc_receivable tienen la misma fórmula (confirmado)
    calc_gqm_final_sold_pricing = (
        gqm_target_sold_pricing
        + gqm_total_change_orders
        + calc_ptl_gc_fee
    )
    calc_acc_receivable = calc_gqm_final_sold_pricing

    # Nivel 5 — dependen de Gqm_final_sold_pricing y Gqm_adj_formula_pricing
    calc_gqm_premium_in_money = (
        calc_gqm_final_sold_pricing - calc_gqm_adj_formula_pricing
    )
    calc_gqm_target_return = (
        (calc_gqm_final_sold_pricing - calc_gqm_adj_formula_pricing)
        / calc_gqm_final_sold_pricing
        if calc_gqm_final_sold_pricing != 0
        else 0.0
    )

    # Nivel 6 — cierre financiero
    calc_gqm_final_form_pricing = (
        sum_adj_formula
        + calc_gqm_total_materials_fees
        + calc_gqm_paid_fees
    )
    calc_gqm_final_adj_form_pricing = calc_gqm_final_form_pricing * 1.027

    # Gqm_final_percentage y Gqm_final_target_return tienen la misma fórmula (confirmado)
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

    # -------------------------------------------------------------------------
    # 7. Retornar todos los campos calculados
    # -------------------------------------------------------------------------
    return {
        # EstimateCost-derived
        "Estimated_rent":             calc_estimated_rent,
        "Estimated_material":         calc_estimated_material,
        "Estimated_city":             calc_estimated_city,
        "Ptl_gc_fee":                 str(calc_ptl_gc_fee),  # tipo string en el modelo
        "Bldg_dept_fees":             calc_bldg_dept_fees,   # list[str] → JSON
        "Gqm_paid_fees":              calc_gqm_paid_fees,
        # Purchase-derived
        "Gqm_total_materials_fees":   calc_gqm_total_materials_fees,
        # Order-derived
        "Tech_formula_pricing":       calc_tech_formula_pricing,
        "Gqm_formula_pricing":        calc_gqm_formula_pricing,
        # Multiplier-derived
        "Gqm_adj_formula_pricing":    calc_gqm_adj_formula_pricing,
        # ChangeOrder + manual inputs
        "Gqm_total_change_orders":    gqm_total_change_orders,
        "Gqm_final_sold_pricing":     calc_gqm_final_sold_pricing,
        "Acc_receivable":             calc_acc_receivable,
        # Pricing returns
        "Gqm_premium_in_money":       calc_gqm_premium_in_money,
        "Gqm_target_return":          calc_gqm_target_return,
        # Financial close
        "Gqm_final_form_pricing":     calc_gqm_final_form_pricing,
        "Gqm_final_adj_form_pricing": calc_gqm_final_adj_form_pricing,
        "Gqm_final_percentage":       calc_gqm_final_percentage,
        "Gqm_final_target_return":    calc_gqm_final_target_return,
        "Gqm_final_prem_in_money":    calc_gqm_final_prem_in_money,
    }


def recalculate_and_apply(job_id: str, session: Session) -> Optional[Job]:
    """
    Calcula los campos derivados del Job y los aplica al objeto en la sesión.
    NO hace commit — el llamador decide cuándo commitear.

    Retorna el objeto Job actualizado, o None si no existe.

    Uso típico:
        recalculate_and_apply(job_id, session)
        session.commit()   # o save_with_retry si tu helper lo incluye
    """
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