
# MAPEO DE LOS CAMPOS PARA ORDER Y CHANGE ORDER

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


# --------- PARA CHANGE ORDER:
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
        11: ["change-order-11"],
        12: ["change-order-12"]
    },
    "PTL": {
        1: ["gqm-change-order-1"],
        2: ["gqm-change-order-2"],
        3: ["gqm-change-order-3"],
        4: ["gqm-change-order-4"]
    }
}
