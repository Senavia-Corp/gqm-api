from ...convert_value_podio import convert_value_for_podio

PTL_FIELD_MAP = {
    "ID_Jobs": "titulo",
    "Client_id": "client",
    "Project_location": "location",
    "ID_Member": "mgmt-member",
    "Job_status": "categoria",
    "Estimated_start_date": "estimated-start-date",

    "Gqm_total_change_orders": "gqm-total-change-orders",
    "Gqm_adj_formula_pricing": "gqm-adj-formula-total-cost",
    "Gqm_target_sold_pricing": "ptl-pricing-target",
    "Gqm_target_return": "gqm-target-ptl-2",
    "Gqm_premium_in_money": "gqm-inc-collected-premium",
    "Gqm_final_sold_pricing": "2025-gqm-final-sold-ptl",
}


def map_job_to_podio_ptl(job_obj):
    payload = {}
    for attr, podio_field in PTL_FIELD_MAP.items():
        value = getattr(job_obj, attr, None)
        if value:
            payload[podio_field] = convert_value_for_podio(podio_field, value)
    return payload
