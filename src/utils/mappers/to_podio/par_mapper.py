from ...convert_value_podio import convert_value_for_podio

PAR_FIELD_MAP = {
    "ID_Jobs": "titulo",
    "Client_id": "client",
    "Job_status": "job-status",
    "Estimated_start_date": "week-assigned",

    "Gqm_formula_pricing": "gqm-formula-pricing-2",
    "Gqm_target_sold_pricing": "gqm-target-sold-par",
    "Gqm_target_return": "gqm-target-par-return-2",
    "Gqm_premium_in_money": "gqm-premium-in-par-2",
}


def map_job_to_podio_par(job_obj):
    payload = {}
    for attr, podio_field in PAR_FIELD_MAP.items():
        value = getattr(job_obj, attr, None)
        if value:
            payload[podio_field] = convert_value_for_podio(podio_field, value)
    return payload
