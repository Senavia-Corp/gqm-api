
# MAPEO DE LOS CAMPOS PARA ORDER Y CHANGE ORDER

# --------- PARA SUBCONTRACTOR:
# Technician x
TECHNICIAN_FIELDS = {
    1: ["technician-2"],
    2: ["technician-2-2"],
    3: ["technician-3"],
    4: ["technician-4"],
    5: ["technician-5"],
    6: ["technician-6"],
    7: ["technician-7"],
    8: ["technician-8"],
    9: ["technician-9"],
    10: ["technician-10"],
    11: ["technician-11"],
    12: ["technician-12"],
    13: ["technician-13"],
    14: ["technician-14"],
    15: ["technician-15"],
    16: ["technician-16"],
    17: ["technician-17"],
    18: ["technician-18"],
    19: ["technician-19"],
    20: ["technician-20"]
}

# --------- PARA ORDER:
# Formula
TECH_FORMULA_FIELDS = {
    "QID": {
        1: ["tech-1-ptl-original-pricing"],
        2: ["tech-2-ptl-original-pricing"],
        3: ["tech-3-ptl-original-pricing"],
        4: ["tech-4-ptl-original-pricing"],
        5: ["labor-tech-5"],
        6: ["labor-tech-6"],
        7: ["labor-tech-7"],
        8: ["labor-tech-8"],
        9: ["labor-tech-9"],
        10: ["labor-tech-10"],
        11: ["labor-tech-11"],
        12: ["labor-tech-12"],
        13: ["tech-13-formula"],
        14: ["tech-14-formula"],
        15: ["tech-15-formula"],
        16: ["tech-16-formula"],
        17: ["tech-17-formula"],
        18: ["tech-18-formula"],
        19: ["tech-19-formula"],
        20: ["tech-20-formula"]
    },
    "PTL": {
        1: ["tech-1-ptl-original-pricing"],
        2: ["tech-2-ptl-original-pricing"],
        3: ["tech-3-ptl-original-pricing"],
        4: ["tech-4-ptl-original-pricing"],
        5: ["tech-5-ptl-original-pricing"],
        6: ["tech-6-ptl-original-pricing"],
        7: ["tech-7-ptl-original-pricing"]
    },
    "PAR": {
        1: ["tech-1-ptl-original-pricing"],
        2: ["tech-2-ptl-original-pricing"],
        3: ["tech-3-formula"],
        4: ["tech-4-formula"]
    }
}

# Adj Formula (solo QID)
TECH_ADJ_FORMULA_FIELDS = {
    "QID": {
        1: ["tech-1-total-payment"],
        2: ["tech-2-total-payment"],
        3: ["tech-3-total-payment"],
        4: ["tech-4-total-payment"],
        5: ["tech-5-adj-formula"],
        6: ["tech-6-adj-formula"],
        7: ["tech-7-adj-formula"],
        8: ["tech-8-adj-formula"],
        9: ["tech-9-adj-formula"],
        10: ["tech-10-adj-formula"],
        11: ["tech-11-adj-formula"],
        12: ["tech-12-adj-formula"],
        13: ["tech-13-adj-formula"],
        14: ["tech-14-adj-formula"],
        15: ["tech-15-adj-formula"],
        16: ["tech-16-adj-formula"],
        17: ["tech-16-adj-formula-2", "tech-17-adj-formula"],
        18: ["tech-18-adj-formula"],
        19: ["tech-19-adj-formula"],
        20: ["tech-20-adj-formula"]
    }
}

# Tech - H.D. / Materials (solo PTL)
TECH_HD_MATERIALS_FIELDS = {
    "PTL": {
        1: ["home-depot-materials"],
        2: ["tech-2-hd-materials"]
    }
}

# Notes (solo PAR)
TECH_NOTES_FIELDS = {
    "PAR": {
        1: ["description"],
        2: ["tech-2-description"],
        3: ["tech-3-description"],
        4: ["tech-4-description"]
    }
}

# Pagos parciales / cuotas (solo PAR — decisión 2026-08-08): la posición en
# la lista es el número de cuota (slot 1..3). Tech 1/2 admiten 3 cheques,
# Tech 3/4 solo 2 (esquema real de la app PAR).
TECH_PAYMENT_FIELDS = {
    "PAR": {
        1: ["check-amount-payment-1", "check-amount-payment-2", "check-amount-payment-3"],
        2: ["check-amount-payment-1-2", "check-amount-payment-2-2", "check-amount-payment-3-2"],
        3: ["tech-3-payment-1", "tech-3-payment-2"],
        4: ["tech-4-payment-1", "tech-4-payment-2"],
    }
}


def collect_payment_slots(fields: list, job_type: str) -> dict:
    """Devuelve {tech_index: {cuota(1..3): monto}} para los tipos con pagos
    parciales (hoy solo PAR). Los montos llegan como strings de money."""
    payment_map = TECH_PAYMENT_FIELDS.get(job_type, {})
    if not payment_map:
        return {}

    out: dict = {}
    for f in fields:
        external_id = f.get("external_id")
        values = f.get("values") or []
        if not external_id or not values:
            continue

        raw = values[0].get("value", values[0])
        if isinstance(raw, dict):
            raw = raw.get("value")
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            continue

        for tech_index, slots in payment_map.items():
            if external_id in slots:
                out.setdefault(tech_index, {})[slots.index(external_id) + 1] = amount
                break
    return out


# Project Change Order
PROJECT_CHANGE_ORDER_FIELDS = {
    "QID": {
        1: ["change-order-1"],
        2: ["change-order-2-2"],
        3: ["change-order-3-2"],
        4: ["change-order-4"],
        5: ["change-order-5"],
        6: ["change-order-6"],
        7: ["change-order-7"],
        8: ["change-order-8"],
        9: ["change-order-9"],
        10: ["change-order-10"],
        11: ["change-order-11"]
    },
    "PTL": {
        1: ["gqm-change-order-1"],
        2: ["gqm-change-order-2"],
        3: ["gqm-change-order-3"],
        4: ["gqm-change-order-4"]
    }
}

# Order Change Orders
ORDER_CHANGE_ORDERS_FIELDS = {
    "QID": {
        1: [
            "tech-1-change-order-3",
            "tech-1-change-order-2-2",
            "tech-1-change-order-2",
            "tech-1-change-order-4",
            "tech-1-change-order-5"
        ],
        2: [
            "tech-2-change-order-1",
            "tech-2-change-order-1-2",
            "tech-2-change-order-3",
            "tech-2-change-order-4",
            "tech-2-change-order-5",
            "tech-2-change-order-6"
        ],
        3: [
            "tech-3-change-order-1",
            "tech-3-change-order-2",
            "tech-3-change-order-3"
        ],
        4: [
            "tech-4-change-order-1",
            "tech-4-change-order-2",
            "tech-4-change-order-3",
            "tech-4-change-order-4",
            "tech-4-change-order-5",
            "tech-4-change-order-6",
            "tech-4-change-order-7",
            "tech-4-change-order-8"
        ],
        5: [
            "material-tech-4",
            "rentals-tech-5",
            "tech-5-change-order-3"
        ],
        6: [
            "material-tech-6",
            "tech-6-change-order-2",
            "tech-6-change-order-3",
            "tech-6-change-order-4",
            "tech-6-change-order-5"
        ],
        7: [
            "material-tech-7",
            "tech-7-change-order-2"
        ],
        8: [
            "material-tech-8",
            "tech-8-change-order-2"
        ],
        9: [
            "material-tech-9",
            "tech-9-change-order-2"
        ],
        10: ["tech-10-change-order-1"],
        11: ["tech-11-change-order-1"],
        12: ["tech-12-change-order-1"],
        13: [
            "tech-13-change-order-1",
            "tech-13-change-order-2",
            "tech-13-change-order-3"
        ],
        14: ["tech-14-change-order-1"],
        15: ["tech-15-change-order-1"],
        16: ["tech-16-change-order-1"],
        17: ["tech-17-change-order-1"],
        18: ["tech-18-change-order-1"],
        19: ["tech-19-change-order-1"],
        20: ["tech-20-change-order-1"]
    },
    "PTL": {
        1: [
            "tech-1-change-order-1",
            "tech-1-change-order-2",
            "tech-1-change-order-3",
            "tech-1-change-order-4"
        ],
        2: [
            "tech-2-change-order-1",
            "tech-2-change-order-1-2",
            "tech-2-change-order-3",
            "tech-2-change-order-4"
        ],
        3: [
            "tech-3-change-order-1",
            "tech-3-change-order-2",
            "tech-3-change-order-3",
            "tech-3-change-order-4"
        ],
        4: [
            "tech-4-change-order-1",
            "tech-4-change-order-2",
            "tech-4-change-order-3",
            "tech-4-change-order-4"
        ],
        5: ["tech-5-change-order-1"],
        6: ["tech-6-change-order-1"],
        7: ["tech-7-change-order-1"]
    }
}


# ==========================================================================
# Qué significa "el slot no viene en el item"  (1-sep-2026)
# ==========================================================================
# Podio OMITE del item los campos vacíos. Como `item_de_confianza` relee
# SIEMPRE el item entero de Podio antes de escribir, un slot que no aparece
# significa "ese técnico ya no está en Podio".
#
# Hasta hoy los dos lectores de órdenes (`jobs_hook_sync` y `sync_orders`)
# construían `tech_data` SOLO con los campos presentes, así que un slot que
# desaparecía entero no se visitaba nunca: `upsert_order` no se llamaba y la
# fila conservaba su `Formula`, sus `Notes` y sus cuotas indefinidamente. Es el
# mismo defecto que el de `job_mapper.campos_vaciables`, pero en filas.
#
# El vaciado parcial (el técnico sigue y se vacía UNO de sus campos) ya
# funcionaba: `upsert_order` recibe None y lo escribe. Lo que faltaba era
# enumerar el universo de slots.

# El universo son los índices con campo de FÓRMULA, porque `Order.tech_field`
# guarda justo ese external_id: un índice sin fórmula no puede tener Order.
# Verificado contra producción el 1-sep-2026: los 29 valores distintos de
# `tech_field` son todos campos de fórmula de su propio tipo de job.

# Cuotas que NO existen en esa app-año (REG-073, medido 2026-08-09 con un GET a
# las 12 apps reales: ~/outputs/gqm-entrega/reports/REG-073-mapper-vs-apps.md).
# Ahí `collect_payment_slots` devuelve {} y pisar `Payment_1..3` borraría un
# dato bueno por un hueco del esquema, no por un vaciado en Podio.
SLOTS_SIN_CUOTAS = {
    ("PAR", 2023): frozenset({3, 4}),
    ("PAR", 2024): frozenset({4}),
}


def slots_vaciables(job_type: str, anio) -> frozenset:
    """Los índices de técnico cuya ausencia SÍ puede vaciar su fila `Order`.

    Fuente única a propósito: la usan los dos lectores para decidir y
    `/admin/podio/obsoletos_ordenes` para medir. Si cada uno tuviera su lista,
    la medida dejaría de decir nada sobre lo que el arreglo hace.

    Sin año devuelve el conjunto vacío —no hay tabla de huecos que consultar—,
    igual que `campos_vaciables`: es el caso de los jobs sembrados por tests
    (`QID80001`, `PAR99901`) y de cualquier `ID_Jobs` que la regla del año no
    reconozca.
    """
    if anio is None:
        return frozenset()
    return frozenset(TECH_FORMULA_FIELDS.get(job_type, {}))


def cuotas_vaciables(job_type: str, anio) -> frozenset:
    """Los slots donde una ausencia puede además vaciar `Payment_1..3`.

    Se cruza con `TECH_PAYMENT_FIELDS` ANTES de restar los huecos por año: los
    cheques parciales solo existen en PAR. En QID y PTL, Podio no tiene campo de
    cuota, asi que un `Payment_N` con valor solo puede haberlo escrito una
    persona por `POST`/`PATCH /order/` —estan en `OrderBase`— y no hay nada en
    Podio con lo que devolverlo. Vaciarlo seria destruirlo sin vuelta.
    Es la misma regla que `upsert_order` ya documenta en su firma: `payments=None`
    para QID/PTL significa NO TOCAR.
    """
    return (slots_vaciables(job_type, anio)
            & frozenset(TECH_PAYMENT_FIELDS.get(job_type, {}))
            ) - SLOTS_SIN_CUOTAS.get((job_type, anio), frozenset())


def cos_declarados(job_type: str) -> set:
    """Los external_ids de change order de NIVEL ORDEN de ese tipo.

    Los de nivel proyecto (`PROJECT_CHANGE_ORDER_FIELDS`) quedan fuera a
    propósito: alimentan `Gqm_total_change_orders` -> `Gqm_final_sold_pricing`
    -> `Acc_receivable`, o sea el lado de los INGRESOS, y ese movimiento se
    mide antes de hacerlo.
    """
    return {slug
            for slugs in ORDER_CHANGE_ORDERS_FIELDS.get(job_type, {}).values()
            for slug in slugs}
