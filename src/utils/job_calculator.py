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
#   1. job_routes.py          → update_job()              (PATCH /jobs/<id>)
#   2. order_routes.py        → create/update/delete order
#   3. purchase_routes.py     → create/update/delete purchase
#   4. estimate_routes.py     → create/update/delete estimate cost
#   5. change_order_routes.py → create/update/delete change order  ← NEW
#   6. webhook.py             → podio_jobs_webhook()      (item.create / item.update)
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

    for start, end, factor in DEFAULT_MULTIPLIER_RANGES:
        if start <= formula_value <= end:
            return factor

    return DEFAULT_MULTIPLIER_FALLBACK


def _resolve_job_id_from_change_order(co: ChangeOrder, session: Session) -> Optional[str]:
    """
    Dado un ChangeOrder, resuelve el ID_Jobs del Job al que pertenece.

    Para change orders generales (ID_Order is None):
        ID_Jobs está directamente en el objeto.

    Para change orders vinculados a una Order (ID_Order is not None):
        Se busca la Order y desde ahí se llega al Job por EstimateCost o por
        job_podio_id, según cómo esté vinculada la Order al Job.
    """
    # Caso 1: change order general — el job_id está directo
    if co.ID_Jobs:
        return co.ID_Jobs

    # Caso 2: change order de Order — llegar al Job via la Order
    if co.ID_Order:
        order = session.exec(
            select(Order).where(Order.ID_Order == co.ID_Order)
        ).first()
        if not order:
            return None

        # Intentar resolver el job por job_podio_id de la Order
        if order.job_podio_id:
            linked_job = session.exec(
                select(Job).where(Job.podio_item_id == order.job_podio_id)
            ).first()
            if linked_job:
                return linked_job.ID_Jobs

        # Intentar resolver el job vía EstimateCost → ID_Jobs
        ec = session.exec(
            select(EstimateCost).where(
                EstimateCost.ID_Order == co.ID_Order,
                EstimateCost.ID_Jobs.is_not(None),
            )
        ).first()
        if ec and ec.ID_Jobs:
            return ec.ID_Jobs

    return None


def recalculate_job_fields(job_id: str, session: Session) -> dict:
    """
    Calcula todos los campos derivados del Job identificado por job_id.

    Retorna un dict { campo_python: valor_calculado }. Retorna {} si el Job
    no existe.
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
    bldg_dept_fees_list: list[float] = []   # float — modelo actualizado

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
            bldg_dept_fees_list.append(
                float(ec.Builder_cost) if ec.Builder_cost is not None else 0.0
            )

    # Gqm_paid_fees = suma directa de los floats
    gqm_paid_fees = sum(bldg_dept_fees_list)

    # -------------------------------------------------------------------------
    # 2. Purchases → Gqm_total_materials_fees
    # -------------------------------------------------------------------------
    purchases = session.exec(
        select(Purchase).where(Purchase.ID_Jobs == job_id)
    ).all()
    gqm_total_materials_fees = sum(float(p.Total_spending or 0) for p in purchases)

    # -------------------------------------------------------------------------
    # 3. Orders → suma de Adj_formula
    #
    #    Vinculación dual: job_podio_id (Podio) y EstimateCost.ID_Order (DB).
    #
    #    Nota: los change orders de Order modifican el Adj_formula de la Order
    #    en Podio, pero aquí leemos el valor ya persistido en Order.Adj_formula.
    #    El change_order_routes dispara este recálculo después de cada mutación,
    #    por lo que el valor recalculado siempre refleja el estado actual de la DB.
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # 4. ChangeOrders GENERALES vinculadas al Job sin Order específica
    #    → afectan Gqm_total_change_orders, Gqm_final_sold_pricing, Acc_receivable
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
    # 5. Campos manuales del Job (inputs del usuario — no se recalculan)
    # -------------------------------------------------------------------------
    gqm_target_sold_pricing = float(job.Gqm_target_sold_pricing or 0)

    # -------------------------------------------------------------------------
    # 6. Cálculo en orden de dependencias
    # -------------------------------------------------------------------------

    # Nivel 1
    calc_estimated_rent           = estimated_rent
    calc_estimated_material       = estimated_material
    calc_estimated_city           = estimated_city
    calc_ptl_gc_fee               = ptl_gc_fee_num        # float nativo
    calc_bldg_dept_fees           = bldg_dept_fees_list   # list[float]
    calc_gqm_paid_fees            = gqm_paid_fees
    calc_gqm_total_materials_fees = gqm_total_materials_fees

    # Nivel 2
    calc_tech_formula_pricing = sum_adj_formula
    calc_gqm_formula_pricing  = (
        sum_adj_formula
        + calc_estimated_material
        + calc_estimated_rent
        + calc_estimated_city
    )

    # Nivel 3
    calc_gqm_adj_formula_pricing = (
        calc_gqm_formula_pricing
        * _resolve_multiplier(calc_gqm_formula_pricing, job, session)
    )

    # Nivel 4
    calc_gqm_final_sold_pricing = (
        gqm_target_sold_pricing
        + gqm_total_change_orders
        + calc_ptl_gc_fee
    )
    calc_acc_receivable = calc_gqm_final_sold_pricing

    # Nivel 5
    calc_gqm_premium_in_money = (
        calc_gqm_final_sold_pricing - calc_gqm_adj_formula_pricing
    )
    calc_gqm_target_return = (
        (calc_gqm_final_sold_pricing - calc_gqm_adj_formula_pricing)
        / calc_gqm_final_sold_pricing
        if calc_gqm_final_sold_pricing != 0
        else 0.0
    )

    # Nivel 6
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

    # -------------------------------------------------------------------------
    # 7. Retornar todos los campos calculados
    # -------------------------------------------------------------------------
    return {
        "Estimated_rent":             calc_estimated_rent,
        "Estimated_material":         calc_estimated_material,
        "Estimated_city":             calc_estimated_city,
        "Ptl_gc_fee":                 calc_ptl_gc_fee,       # float
        "Bldg_dept_fees":             calc_bldg_dept_fees,   # list[float]
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
    """
    Calcula los campos derivados del Job y los aplica al objeto en la sesión.
    NO hace commit — el llamador decide cuándo commitear.

    Retorna el objeto Job actualizado, o None si no existe.
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


def recalculate_and_apply_from_change_order(
    change_order: ChangeOrder, session: Session
) -> Optional[Job]:
    """
    Wrapper para disparar el recálculo del Job a partir de un ChangeOrder,
    resolviendo automáticamente el job_id independientemente de si el CO
    es general (ID_Jobs directo) o está vinculado a una Order (ID_Order).

    Retorna el Job actualizado, o None si no se pudo resolver el job_id.
    """
    job_id = _resolve_job_id_from_change_order(change_order, session)
    if not job_id:
        return None
    return recalculate_and_apply(job_id, session)