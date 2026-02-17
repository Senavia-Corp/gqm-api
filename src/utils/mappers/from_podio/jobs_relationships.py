from sqlmodel import select
from src.models.ClientModel import Client
from src.models.BldgDeptModel import BuildingDept
from src.models.link_models.JobMember import JobMemberLink


# MAPEO PARA RELACIÓN CON CLIENT Y BUILDING DEPARTMENT
RELATION_CONFIG = {
    "client": {
        "model": Client,
        "fk_field": "ID_Client",
        "external_id": "relationship",
        "internal_id": "ID_Client"
    },
    "building_dept": {
        "model": BuildingDept,
        "fk_field": "ID_BldgDept",
        "external_id": "bldg-dept",
        "internal_id": "ID_BldgDept"
    },
}


# MAPEO PARA RELACIÓN ENTRE MEMBER Y JOB
JOB_MEMBER_FIELDS = {

    # PAR
    ("PAR", 2024): {
        "acc-rep-selling": {"type": "app", "rol": "Acc Rep Selling"}
    },
    ("PAR", 2025): {
        "acc-rep-selling": {"type": "app", "rol": "Acc Rep Selling"}
    },
    ("PAR", 2026): {
        "acc-rep-selling": {"type": "app", "rol": "Acc Rep Selling"}
    },

    # PTL
    ("PTL", 2023): {
        "member": {"type": "contact", "rol": "Mgmt Member"}
    },
    ("PTL", 2024): {
        "member": {"type": "contact", "rol": "Mgmt Member"}
    },
    ("PTL", 2025): {
        "relationship-2": {"type": "app", "rol": "Mgmt Member"}
    },
    ("PTL", 2026): {
        "relationship-2": {"type": "app", "rol": "Mgmt Member"}
    },

    # QID
    ("QID", 2023): {
        "members": {"type": "contact", "rol": "Selling Member"},
        "mgmt-member": {"type": "contact", "rol": "Mgmt Member"},
        "lead-member": {"type": "contact", "rol": "Lead Member"}
    },
    ("QID", 2024): {
        "relation-rep": {"type": "app", "rol": "Acc Rep Selling"},
        "mgmt-member-2": {"type": "app", "rol": "Mgmt Member"},
        "lead-member": {"type": "contact", "rol": "Lead Member"}
    },
    ("QID", 2025): {
        "relation-rep": {"type": "app", "rol": "Acc Rep Selling"},
        "mgmt-member-2": {"type": "app", "rol": "Mgmt Member"},
        "lead-member": {"type": "contact", "rol": "Lead Member"}
    },
    ("QID", 2026): {
        "relation-rep": {"type": "app", "rol": "Acc Rep Selling"},
        "mgmt-member-2": {"type": "app", "rol": "Mgmt Member"},
        "lead-member": {"type": "contact", "rol": "Lead Member"}
    }
}


# CREAR LINK ENTRE MEMBER Y JOB
def upsert_job_member_link(
    session,
    job_id: str,
    member_id: str,
    rol: str,
    dry_run: bool = False
):
    created = 0
    updated = 0

    link = session.exec(
        select(JobMemberLink).where(
            JobMemberLink.job_id == job_id,
            JobMemberLink.member_id == member_id
        )
    ).first()

    if link:
        if link.rol != rol:
            updated += 1
            if not dry_run:
                link.rol = rol
                session.add(link)
        return created, updated

    created += 1
    if not dry_run:
        session.add(
            JobMemberLink(
                job_id=job_id,
                member_id=member_id,
                rol=rol
            )
        )

    return created, updated
