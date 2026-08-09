# ========================== JOBS TIPO QID ========================== #
# HUECO VERIFICADO (GET /app/28087463, 2026-08-09 — REG-071): la app QID 2023
# NO tiene equivalentes de Gqm_paid_fees ni Bldg_dept_fees. `calculation-10` /
# `bldg-fees-*` no existen; `bldg-dept` es la RELACIÓN al Building Dept (tipo
# app, no money) y `paid-in-full` está borrado. En items 2023 esos campos no
# sincronizan desde Podio: los gobierna el recálculo local (job_calculator).
# NO aliasar `bldg-dept` ni `amount-paid-to-date` aquí — no son equivalentes.
FIELD_ALIASES_QID = {
    "Project_location": {
        "field_id": [274767587, 268722156, 258250427, 246058264],
        "external_ids": ["project-location"]
    },
    "Job_status": {
        "field_id": [274767590, 268722160, 258250430, 246058266],
        "external_ids": ["job-status"]
    },
    "Estimated_completion_date": {
        "field_id": [274767591, 274451708, 258250454, 247690177],
        "external_ids": ["expected-completioninvoice", "expected-completion-date"]
    },
    "Project_name": {
        "field_id": [274767592, 268722162, 259349293, 246058268],
        "external_ids": ["project-name-2", "project-name"]
    },
    "Po_wtn_wo": {
        "field_id": [274767593, 268722163, 258250432],
        "external_ids": ["project-name"]
    },
    "Service_type": {
        "field_id": [274767595, 268722165, 258250434, 246058289],
        "external_ids": ["service-type"]
    },
    "Date_assigned": {
        "field_id": [274767596, 268722166, 258250435, 246058291],
        "external_ids": ["date-received"]
    },
    "Additional_detail": {
        "field_id": [274767597, 268722167, 258250436, 246058290],
        "external_ids": ["superintendent"]
    },
    "Tech_formula_pricing": {
        "field_id": [274767599, 268722169, 258250438, 246828022],
        "external_ids": ["tech-formula-pricing"]
    },
    "Estimated_rent": {
        "field_id": [274767600, 268722170, 258250441, 246826404],
        "external_ids": ["estimated-hoa-admin-total"]
    },
    "Estimated_material": {
        "field_id": [274767601, 268722171, 258250439, 246825473],
        "external_ids": ["estimated-material-total"]
    },
    "Estimated_city": {
        "field_id": [274767602, 268722172, 258250440, 246058279],
        "external_ids": ["fees-and-cost"]
    },
    "Gqm_formula_pricing": {
        "field_id": [274767603, 268722173, 258250442, 246058270],
        "external_ids": ["gqm-formula-total-cost"]
    },
    "Gqm_adj_formula_pricing": {
        "field_id": [274767605, 268722175, 258250444, 246813608],
        "external_ids": ["gqm-adj-formula-pricing"]
    },
    "Gqm_target_sold_pricing": {
        "field_id": [274767606, 268722176, 258250445, 246058271],
        "external_ids": ["gqm-target-sold-price"]
    },
    "Gqm_target_return": {
        "field_id": [274767607, 268722177, 258250446, 246058276],
        "external_ids": ["gross-profit-margin"]
    },
    "Gqm_premium_in_money": {
        "field_id": [274767608, 268722178, 258250448, 246058275],
        "external_ids": ["gqm-pricing-return-premium-in"]
    },
    "Gqm_final_sold_pricing": {
        "field_id": [274767609, 268722179, 258250450, 246058273],
        "external_ids": ["gqm-final-pricing"]
    },
    "Gqm_final_percentage": {
        "field_id": [274767610, 268722180, 258250447, 256910466],
        "external_ids": ["gqm-final"]
    },
    "Pricing_target": {
        "field_id": [274767611, 268722181, 258250449, 246814666],
        "external_ids": ["pricing-target"]
    },
    "Gqm_total_change_orders": {
        "field_id": [274767613, 268722189, 258250457, 246058272],
        "external_ids": ["total-change-orders"]
    },
    "Permit": {
        "field_id": [274767626, 268722196, 258250453, 246077012],
        "external_ids": ["permit"]
    },
    "Gqm_paid_fees": {
        "field_id": [274767628, 269478266],
        "external_ids": ["calculation-10"]
    },
    "Bldg_dept_fees": {
        "field_id": [274767629, 274767630, 274767631, 269478197, 269478265, 269478318],
        "external_ids": ["bldg-fees-1", "bldg-fees-2", "bldg-dept-fees-3"],
        "multi": True
    },
    "Gqm_total_materials_fees": {
        "field_id": [274767634, 268722200, 258250466, 246315516],
        "external_ids": ["materials-purchased-total-2"]
    },
    "Acc_receivable": {
        "field_id": [274767753, 268722317, 258250574, 246058371],
        "external_ids": ["acc-receivable"]
    },
    "Gqm_final_form_pricing": {
        "field_id": [274767754, 268722318, 258250575, 246827281],
        "external_ids": ["gqm-final-formula-pricing"]
    },
    "Gqm_final_adj_form_pricing": {
        "field_id": [274767755, 268722319, 258250576, 246827357],
        "external_ids": ["gqm-final-adj-formula-pricing"]
    },
    "Gqm_final_target_return": {
        "field_id": [274767756, 268722320, 258250577, 246827635],
        "external_ids": ["gqm-final-target-return"]
    },
    "Gqm_final_prem_in_money": {
        "field_id": [274767757, 268722321, 267692180, 266153349],
        "external_ids": ["gqm-final-premium-pricing", "gqm-final-premium-in"]
    }
}

# ========================== JOBS TIPO PTL ========================== #
# HUECO DOCUMENTADO (REG-011): la app PTL 2026 no tiene `deadline` ni
# `date-received`; solo `estimated-start-date`, que NO es semánticamente la
# fecha de completado → no se aliasa. En items 2026 esos dos campos quedan
# sin mapear (warning en logs).
# DECISIÓN (DECISIONES-CONFIRMADAS.md): PTL no usa pagos parciales —
# `payment-received-1/2/3` y `payment-date-and-check-*` se ignoran a propósito.
FIELD_ALIASES_PTL = {
    "Project_location": {
        "field_id": [275089542, 268722716, 259504198, 246476769],
        "external_ids": ["location"]
    },
    "Job_status": {
        "field_id": [275089545, 268722721, 259504203, 246476772],
        "external_ids": ["status"]
    },
    "Estimated_completion_date": {
        "field_id": [259504207, 246476782],
        "external_ids": ["deadline"]
    },
    "Ptl_Superintendent": {
        "field_id": [275089546, 268722722, 259504204, 246476773],
        "external_ids": ["superintendent"]
    },
    "Ptl_property_id": {
        "field_id": [275089547, 268722723, 259504205, 246476774],
        "external_ids": ["title"]
    },
    "Estimated_start_date": {
        "field_id": [275089548, 268722724, 259504206, 246476781],
        "external_ids": ["estimated-start-date"]
    },
    "Date_Received": {
        "field_id": [259504201, 246476780],
        "external_ids": ["date-received"]
    },
    "Gqm_target_sold_pricing": {
        "field_id": [277037708, 275089550, 268722727, 259504209, 246476784],
        "external_ids": ["money"]
    },
    "Ptl_gc_fee": {
        "field_id": [277037709, 275089551, 268722728, 259504210, 246476785],
        "external_ids": ["money-2"]
    },
    "Estimated_material": {
        "field_id": [277037710, 275089552, 268722729, 259504211, 246476791],
        "external_ids": ["fees-and-cost"]
    },
    "Gqm_total_change_orders": {
        "field_id": [277037711, 275089553, 268722730, 259504212, 246832294],
        "external_ids": ["gqm-total-change-orders"]
    },
    "Gqm_formula_pricing": {
        "field_id": [275089556, 268722733, 259504215, 246476777],
        "external_ids": ["gqm-formula-total-cost"]
    },
    "Gqm_adj_formula_pricing": {
        "field_id": [275089557, 268722734, 259504216, 246831970],
        "external_ids": ["gqm-adj-formula-total-cost"]
    },
    "Gqm_target_return": {
        "field_id": [275089558, 268722735, 259504217, 246476779],
        "external_ids": ["gross-profit-margin"]
    },
    "Pricing_target": {
        "field_id": [275089559, 268722736, 259504218, 247636782],
        "external_ids": ["pricing-target"]
    },
    "Gqm_premium_in_money": {
        "field_id": [275089560, 268722737, 259504219, 246476778],
        "external_ids": ["gqm-inc-target"]
    },
    "Gqm_final_sold_pricing": {
        "field_id": [275089561, 268722738, 259504220, 246476792],
        "external_ids": ["total-project-cost"]
    },
    "Acc_receivable": {
        "field_id": [275089616, 269475426],
        "external_ids": ["acc-receivable"]
    },
}

# ========================== JOBS TIPO PAR ========================== #
FIELD_ALIASES_PAR = {
    "Date_assigned": {
        "field_id": [275089685, 269436484, 259510252, 246477047],
        "external_ids": ["date-received"]
    },
    "Job_status": {
        "field_id": [275089686, 269436485, 259510253, 246477048],
        "external_ids": ["job-status"]
    },
    "Gqm_formula_pricing": {
        "field_id": [275089688, 269436499, 259510263, 246477058],
        "external_ids": ["gqm-formula-total-cost"]
    },
    "Gqm_target_sold_pricing": {
        "field_id": [275089689, 269436500, 259510264, 246477059],
        "external_ids": ["gqm-target-sold-price"]
    },
    "Pricing_target": {
        "field_id": [275089690, 269436504, 261854267],
        "external_ids": ["par-pricing-target"]
    },
    "Gqm_premium_in_money": {
        "field_id": [275089691, 269436502, 259510266, 246477061],
        "external_ids": ["gqm-pricing-return-premium-in"]
    },
    "Gqm_target_return": {
        "field_id": [275089692, 269436503, 259510267, 246477062],
        "external_ids": ["gross-profit-margin"]
    },
    "Acc_receivable": {
        "field_id": [275089711, 269436506, 259510269, 246477064],
        "external_ids": ["acc-receivable"]
    },
    "Po_wtn_wo": {
        "field_id": [275089713, 269436508, 259510271, 246477066],
        "external_ids": ["payment-date-and-number-1"]
    }
}
