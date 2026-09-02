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
        "external_ids": [
            "bldg-fees-1",
            "bldg-fees-2",
            "bldg-dept-fees-3"
        ],
        "type": "money",
        "multi": True
    },
    "Purchases_list": {
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


# ================== Vaciado explícito desde el PATCH de un job ================== #
# Traduce los atributos del modelo que una petición pidió VACIAR a los `external_id`
# que `limpiar_slots` sabe borrar. Sólo texto: un `[]` en un `money` borra el importe
# en Podio (fix/patch-delete-no-borran-dinero) y en un `date` borra la fecha, así que
# esos tipos siguen omitiéndose cuando no hay valor, exactamente como hasta hoy.

_BASES = {"QID": BASE_QID_FIELDS, "PTL": BASE_PTL_FIELDS, "PAR": BASE_PAR_FIELDS}

_VACIABLES = {"text", "location"}


def external_ids_de(job_type, attrs):
    """`external_id` de los campos de texto indicados. Todo lo demás se ignora.

    Los campos `multi` quedan fuera solos: declaran `external_ids` (plural), no
    `external_id`. Las relaciones (`ID_Client`, `ID_BldgDept`) tampoco están en
    estos catálogos, así que desvincular sigue sin pasar por aquí.

    `Ptl_property_id` mapea al `external_id` "title" y estuvo excluido por temor a
    que fuese el título obligatorio del item. Medido el 2-sep-2026 contra Podio:
    en la app PTL de producción (30577946) ese campo es `required=False`, se llama
    "Property ID", 1 de 38 items ya lo tiene vacío, y el título visible del item
    sale de otro campo. Un `PUT` con `{"title": []}` sobre la app de prueba
    devolvió 200 y lo vació. No hay motivo para excluirlo.
    """
    base = _BASES.get(job_type, {})
    return [
        base[a]["external_id"]
        for a in attrs
        if a in base
        and base[a].get("type") in _VACIABLES
    ]
