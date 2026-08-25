# MAPEADOR PARA MANDAR ORDER A LOS CAMPOS DE JOB EN PODIO

# ================== QID ================== #
ORDER_QID_FIELDS = {
    "Formula": {
        1: "tech-1-ptl-original-pricing",
        2: "tech-2-ptl-original-pricing",
        3: "tech-3-ptl-original-pricing",
        4: "tech-4-ptl-original-pricing",
        5: "labor-tech-5",
        6: "labor-tech-6",
        7: "labor-tech-7",
        8: "labor-tech-8",
        9: "labor-tech-9",
        10: "labor-tech-10",
        11: "labor-tech-11",
        12: "labor-tech-12",
        13: "tech-13-formula",
        14: "tech-14-formula",
        15: "tech-15-formula",
        16: "tech-16-formula",
        # REG-076: el lector (from_podio) cubre hasta 20; el writer llegaba
        # solo a 16 → subs en 17..20 sin destino de fórmula.
        #
        # M10, matizado el 19-ago-2026 contra el esquema real de las 4 apps: NO
        # se pueden borrar. La app QID **2023 SÍ tiene** los técnicos 17-20, y
        # 2024 tiene el 17. Los que no existen son 17-20 en 2025/2026 y 18-20 en
        # 2024. Escribir ahí da `field.not.found` sólo en esos años.
        #
        # La deriva la vigila la prueba de contrato esquema↔mapas, que corre POR
        # AÑO; recortar el mapa a secas rompería 2023.
        17: "tech-17-formula",
        18: "tech-18-formula",
        19: "tech-19-formula",
        20: "tech-20-formula"
    },
    "ID_Subcontractor": {
        1: "technician-2",
        2: "technician-2-2",
        3: "technician-3",
        4: "technician-4",
        5: "technician-5",
        6: "technician-6",
        7: "technician-7",
        8: "technician-8",
        9: "technician-9",
        10: "technician-10",
        11: "technician-11",
        12: "technician-12",
        13: "technician-13",
        14: "technician-14",
        15: "technician-15",
        16: "technician-16",
        17: "technician-17",
        18: "technician-18",
        19: "technician-19",
        20: "technician-20"
    }
}


# ================== PTL ================== #
ORDER_PTL_FIELDS = {
    "Formula": {
        1: "tech-1-ptl-original-pricing",
        2: "tech-2-ptl-original-pricing",
        3: "tech-3-ptl-original-pricing",
        4: "tech-4-ptl-original-pricing",
        5: "tech-5-ptl-original-pricing",
        6: "tech-6-ptl-original-pricing",
        7: "tech-7-ptl-original-pricing"
    },
    "ID_Subcontractor": {
        1: "technician-2",
        2: "technician-2-2",
        3: "technician-3",
        4: "technician-4",
        5: "technician-5",
        6: "technician-6",
        7: "technician-7"
    },
    "Ptl_hd_materials": {
        1: "home-depot-materials",
        2: "tech-2-hd-materials"
    }
}


# ================== PAR ================== #
ORDER_PAR_FIELDS = {
    "Formula": {
        1: "tech-1-ptl-original-pricing",
        2: "tech-2-ptl-original-pricing",
        3: "tech-3-formula",
        4: "tech-4-formula"
    },
    "ID_Subcontractor": {
        1: "technician-2",
        2: "technician-2-2",
        3: "technician-3",
        4: "technician-4"
    },
    "Notes": {
        1: "description",
        2: "tech-2-description",
        3: "tech-3-description",
        4: "tech-4-description"
    }
}

# MAPEADOR PARA MANDAR CHANGE ORDER A LOS CAMPOS DE JOB EN PODIO

# ================== QID PROJECT CHANGE ORDERS ================== #
PROJECT_CO_QID_FIELDS = {
    1: "change-order-1",
    2: "change-order-2-2",
    3: "change-order-3-2",
    4: "change-order-4",
    5: "change-order-5",
    6: "change-order-6",
    7: "change-order-7",
    8: "change-order-8",
    9: "change-order-9",
    10: "change-order-10",
    11: "change-order-11"
}

# ================== QID ORDER CHANGE ORDERS ================== #
ORDER_CO_QID_FIELDS = {
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
    # REG-076: paridad con el lector (ORDER_CHANGE_ORDERS_FIELDS) hasta 20.
    # Ver la nota de M10 arriba: existen en 2023, no en 2025/2026.
    17: ["tech-17-change-order-1"],
    18: ["tech-18-change-order-1"],
    19: ["tech-19-change-order-1"],
    20: ["tech-20-change-order-1"]
}


# ================== PTL PROJECT CHANGE ORDERS ================== #
PROJECT_CO_PTL_FIELDS = {
    1: "gqm-change-order-1",
    2: "gqm-change-order-2",
    3: "gqm-change-order-3",
    4: "gqm-change-order-4"
}

# ================== PTL ORDER CHANGE ORDERS ================== #
ORDER_CO_PTL_FIELDS = {
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
