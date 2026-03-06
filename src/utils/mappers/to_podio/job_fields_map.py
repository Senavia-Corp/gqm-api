# ========================== JOBS TIPO QID ========================== #
BASE_QID_FIELDS = {
    "Project_location": {
        "external_id": "project-location",
        "type": "location"
    },
    "Job_status": {
        "external_id": "job-status",
        "type": "category"
    },
    "Estimated_completion_date": {
        "external_id": "expected-completioninvoice",
        "type": "date"
    },
    "Project_name": {
        "external_id": "project-name-2",
        "type": "text"
    },
    "Po_wtn_wo": {
        "external_id": "project-name",
        "type": "text"
    },
    "Service_type": {
        "external_id": "service-type",
        "type": "category"
    },
    "Date_assigned": {
        "external_id": "date-received",
        "type": "date",
        "end_attr": "Date_assigned_end",
        "no_end": True
    },
    "Additional_detail": {
        "external_id": "superintendent",
        "type": "text"
    },
    "Estimated_rent": {
        "external_id": "estimated-hoa-admin-total",
        "type": "money"
    },
    "Estimated_material": {
        "external_id": "estimated-material-total",
        "type": "money"
    },
    "Estimated_city": {
        "external_id": "fees-and-cost",
        "type": "money"
    },
    "Gqm_target_sold_pricing": {
        "external_id": "gqm-target-sold-price",
        "type": "money"
    },
    "Pricing_target": {
        "external_id": "pricing-target",
        "type": "category"
    },
    "Permit": {
        "external_id": "permit",
        "type": "category"
    },
    "Bldg_dept_fees": {
        "external_ids": [
            "bldg-fees-1",
            "bldg-fees-2",
            "bldg-dept-fees-3"
        ],
        "type": "money",
        "multi": True
    }
}


# ========================== JOBS TIPO PTL ========================== #
BASE_PTL_FIELDS = {
    "Project_location": {
        "external_id": "location",
        "type": "location"
    },
    "Job_status": {
        "external_id": "status",
        "type": "category"
    },
    "Ptl_Superintendent": {
        "external_id": "superintendent",
        "type": "text"
    },
    "Ptl_property_id": {
        "external_id": "title",
        "type": "text"
    },
    "Estimated_start_date": {
        "external_id": "estimated-start-date",
        "type": "date",
        "end_attr": "Estimated_start_date_end"
    },
    "Gqm_target_sold_pricing": {
        "external_id": "money",
        "type": "money"
    },
    "Ptl_gc_fee": {
        "external_id": "money-2",
        "type": "money"
    },
    "Estimated_material": {
        "external_id": "fees-and-cost",
        "type": "money"
    },
    "Pricing_target": {
        "external_id": "pricing-target",
        "type": "category"
    }
}


# ========================== JOBS TIPO PAR ========================== #

BASE_PAR_FIELDS = {
    "Date_assigned": {
        "external_id": "date-received",
        "type": "date",
        "end_attr": "Date_assigned_end"
    },
    "Job_status": {
        "external_id": "job-status",
        "type": "category"
    },
    "Gqm_target_sold_pricing": {
        "external_id": "gqm-target-sold-price",
        "type": "money"
    },
    "Pricing_target": {
        "external_id": "par-pricing-target",
        "type": "category"
    },
    "Po_wtn_wo": {
        "external_id": "payment-date-and-number-1",
        "type": "text"
    }
}
