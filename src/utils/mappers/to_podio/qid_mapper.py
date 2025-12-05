from ...convert_value_podio import convert_value_for_podio

QID_FIELD_MAP = {
    "ID_Jobs": "id-projects-workorder",
    "ID_Client": "client-2",
    "Project_location": "project-location-2",
    "Job_status": "job-status-2",
    "Project_name": "project-name-2",
    "Po_wtn_wo": "powtnwo",
    "Service_type": "service-type-3",
    "Date_assigned": "date-assigned-2",

    "Gqm_adj_formula_pricing": "gqm-adj-formula-pricing-2",
    "Gqm_target_sold_pricing": "gqm-target-sold-pricing",
    "Gqm_target_return": "gqm-target-return",
    "Gqm_premium_in_money": "2023-gqm-final",
    "Gqm_final_sold_pricing": "2023-gqm-premium-in",
    "Gqm_final_percentage": "gqm-final-sold-pricing",
    "Gqm_total_change_orders": "gqm-total-change-orders-2",
}


def map_job_to_podio_qid(job_obj):
    payload = {}
    for attr, podio_field in QID_FIELD_MAP.items():
        value = getattr(job_obj, attr, None)
        if value is not None:
            payload[podio_field] = convert_value_for_podio(podio_field, value)
    return payload
