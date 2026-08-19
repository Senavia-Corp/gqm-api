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
        "no_end": True,
        "with_time": True
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
        # `familia` enlaza con src/utils/podio_slots.py: cada BD fee aprobado
        # escribe en el hueco que declara ocupar, no en el que le toque por
        # orden de creación.
        "familia": "QID.bldg_dept_fees",
        "external_ids": [
            "bldg-fees-1",
            "bldg-fees-2",
            "bldg-dept-fees-3"
        ],
        "type": "money",
        "multi": True
    },
    "Purchases_list": {
        # Pool COMPARTIDO por los alquileres aprobados y las compras: por eso
        # los alquileres acaban en huecos etiquetados «PURCHASE» (defecto G1).
        "familia": "QID.purchases_list",
        "external_ids": [
            "materials-purchased-1-2",
            "materials-purchased-2",
            "materials-purchased-3",
            "material-purchase-4",
            "material-purchase-5",
            "material-purchase-6",
            "material-purchase-7",
            "material-purchase-8",
            "material-purchase-9",
            "material-purchase-10",
            "material-purchase-11",
            "material-purchase-12",
            "material-purchase-13"
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
        "end_attr": "Estimated_start_date_end",
        "with_time": False
    },
    "Gqm_target_sold_pricing": {
        "external_id": "money",
        "type": "money"
    },
    "Ptl_gc_fee": {
        "external_id": "money-2",
        "type": "money"
    },
    # M8 · «PTL no usa materiales, el campo sobra» (Sebastian, 18-ago-2026).
    # Este es el PASO DE CODIGO: la app deja de escribir `fees-and-cost` en PTL.
    # Retirar el campo de las apps PTL de Podio es el paso siguiente, y va
    # despues, nunca antes — al reves convierte el mapeo en un defecto de
    # clase A (el codigo escribiendo a un campo que ya no existe).
    #
    # OJO al slug, que engana: `fees-and-cost` se llama «Estimated City Permits
    # (total)» en QID y recibe los BD FEES; en PTL se llama «GQM Estimated
    # Material (total)» y recibe los MATERIALES. Mismo slug, dos conceptos.
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
        "end_attr": "Date_assigned_end",
        "with_time": False
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
