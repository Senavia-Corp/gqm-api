# MAPEO PARA RELACIONAR MEMBER CON SU RESPECTIVO CAMPO EN PODIO
JOB_MEMBER_PODIO_MAP = {
    "QID": {
        "Acc Rep Selling": {"external_id": "relation-rep", "type": "app"},
        "Mgmt Member": {"external_id": "mgmt-member-2", "type": "app"},
        "Lead Member": {"external_id": "lead-member", "type": "contact"},
    },
    "PTL": {
        "Mgmt Member": {"external_id": "relationship-2", "type": "app"},
    },
    "PAR": {
        "Acc Rep Selling": {"external_id": "acc-rep-selling", "type": "app"},
    }
}


# MAPEO Y HELPER PARA RELACIÓN CON SUBCONTRACTOR
TECHNICIAN_LIMITS = {
    "QID": 16,
    "PTL": 7,
    "PAR": 4
}


def get_technician_fields(job_type):
    limit = TECHNICIAN_LIMITS.get(job_type, 0)
    fields = []

    for i in range(1, limit + 1):
        if i == 1:
            fields.append("technician-2")
        elif i == 2:
            fields.append("technician-2-2")
        else:
            fields.append(f"technician-{i}")

    return fields
