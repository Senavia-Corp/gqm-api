#!/usr/bin/env python3
"""Seed idempotente de RBAC para DESARROLLO (Fase 1).

Crea/actualiza los 4 roles del modelo aprobado, sus permission documents
(IAM JSONB) y los usuarios de prueba @senavia-test.com. Re-ejecutable:
los documentos de política se sobreescriben con lo definido aquí.

Uso (desde la raíz del repo, con el .env de dev):
    SEED_DEV_PASSWORD=... .venv/bin/python scripts/seed_rbac.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decouple import config  # noqa: E402

# Guardas de aislamiento: este seed solo corre contra Neon develop en modo test.
if "ep-sparkling-sound" not in config("DATABASE_URL", default=""):
    sys.exit("⛔ DATABASE_URL no apunta a Neon develop — abortado")
if config("APP_ENV", default="") != "test":
    sys.exit("⛔ APP_ENV != test — abortado")

from sqlmodel import select  # noqa: E402
from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.RoleModel import Role  # noqa: E402
from src.models.PermissionModel import Permission  # noqa: E402
from src.models.MemberModel import Member  # noqa: E402
from src.models.link_models.PermissionLinks import PermissionRoleLink  # noqa: E402
from src.utils.id_generator import generate_custom_id  # noqa: E402
from src.utils.middleware.auth.password_hashing import hash_password  # noqa: E402

ROLES = ["Full Admin", "GQM Member", "Subcontractor", "Technical"]

# Documentos de política por rol (modelo de 4 roles aprobado, B2).
# Vocabulario: {resource}:{read|create|update|delete} + fijos iam:manage,
# qbo:manage, admin:sync, job:force_delete (ver protect_blueprint).
ROLE_POLICIES = {
    "Full Admin": {
        "Name": "full-admin-all",
        "Description": "Acceso total",
        "Document": {"Statement": [{"Effect": "Allow", "Action": ["*"], "Resource": ["*"]}]},
    },
    "GQM Member": {
        "Name": "gqm-member-operativo",
        "Description": "CRUD operativo; sin gestión de roles/usuarios, QBO ni admin",
        "Document": {"Statement": [
            {"Effect": "Allow", "Action": ["*"], "Resource": ["*"]},
            {"Effect": "Deny", "Action": [
                "iam:*", "qbo:*", "admin:*",
                "role:create", "role:update", "role:delete",
                "permission:create", "permission:update", "permission:delete",
                "member:create", "member:update", "member:delete",
                "job:force_delete",
            ], "Resource": ["*"]},
        ]},
    },
    "Subcontractor": {
        "Name": "subcontractor-portal",
        "Description": "Portal de subcontratista: solo lo suyo (scoping en API)",
        "Document": {"Statement": [{"Effect": "Allow", "Action": [
            "job:read", "job:read_basics",
            "finance:read",
            "tasks:read", "tasks:read_own", "tasks:create", "tasks:update",
            "subcontractor:read", "technician:read", "skill:read",
            "attachment:read", "attachment:read_technicians",
            "certificate:read",
        ], "Resource": ["*"]}]},
    },
    "Technical": {
        "Name": "technical-portal",
        "Description": "Portal de técnico: solo lo asignado (scoping en API)",
        "Document": {"Statement": [{"Effect": "Allow", "Action": [
            "job:read_basics",
            "tasks:read", "tasks:read_own", "tasks:update",
            "technician:read", "skill:read",
            "attachment:read", "attachment:read_technicians",
        ], "Resource": ["*"]}]},
    },
}

# (email, nombre, rol) — usuarios Member de prueba.
MEMBERS = [
    ("admin-dev@senavia-test.com", "DEV Admin", "Full Admin"),
    ("member-dev@senavia-test.com", "DEV Member", "GQM Member"),
]

# Portal: el sub usa rol (Subcontractor.ID_Role); el técnico no tiene rol en
# el modelo — su política se enlaza directa vía permission_tech.
SUBCONTRACTOR_USER = ("sub-dev@senavia-test.com", "DEV Subcontractor")
TECHNICIAN_USER = ("tech-dev@senavia-test.com", "DEV Technician")


def seed_password() -> str:
    password = os.environ.get("SEED_DEV_PASSWORD") or config("SEED_DEV_PASSWORD", default="")
    if not password:
        sys.exit("⛔ falta SEED_DEV_PASSWORD (env o .env)")
    return password


def upsert_role(session, name: str) -> Role:
    role = session.exec(select(Role).where(Role.Name == name)).first()
    if not role:
        role = Role(Name=name, Description=f"{name} (seed dev)", Active=True)
        role.ID_Role = generate_custom_id(session, Role, "ID_Role", "ROL")
        session.add(role)
        session.commit()
        session.refresh(role)
        print(f"  + rol {role.ID_Role} «{name}»")
    return role


def upsert_policy(session, role: Role, spec: dict) -> Permission:
    perm = session.exec(select(Permission).where(Permission.Name == spec["Name"])).first()
    if not perm:
        perm = Permission(**spec, Active=True)
        perm.ID_Permission = generate_custom_id(session, Permission, "ID_Permission", "PERM")
    else:
        perm.Document = spec["Document"]
        perm.Active = True
    session.add(perm)
    session.commit()
    session.refresh(perm)
    if not session.get(PermissionRoleLink, (perm.ID_Permission, role.ID_Role)):
        session.add(PermissionRoleLink(permission_id=perm.ID_Permission, role_id=role.ID_Role))
        session.commit()
        print(f"  + política «{spec['Name']}» → {role.Name}")
    return perm


def upsert_member(session, email: str, name: str, role: Role) -> None:
    member = session.exec(select(Member).where(Member.Email_Address == email)).first()
    if not member:
        member = Member(
            Member_Name=name,
            Company_Role="QA Dev",
            Email_Address=email,
            Password=hash_password(seed_password()),
            ID_Role=role.ID_Role,
        )
        member.ID_Member = generate_custom_id(session, Member, "ID_Member", "MEM")
        print(f"  + member {email} ({role.Name})")
    else:
        member.Password = hash_password(seed_password())
        member.ID_Role = role.ID_Role
    session.add(member)
    session.commit()


def upsert_subcontractor(session, email: str, name: str, role: Role) -> None:
    from src.models.SubcontractorModel import Subcontractor

    sub = session.exec(select(Subcontractor).where(
        Subcontractor.Email_Address == email)).first()
    if not sub:
        sub = Subcontractor(Name=name, Organization=name, Email_Address=email)
        sub.ID_Subcontractor = generate_custom_id(
            session, Subcontractor, "ID_Subcontractor", "SUBC")
        print(f"  + subcontractor {email}")
    sub.Password = hash_password(seed_password())
    sub.ID_Role = role.ID_Role
    session.add(sub)
    session.commit()


def upsert_technician(session, email: str, name: str, policy: "Permission") -> None:
    from src.models.TechnicianModel import Technician
    from src.models.link_models.PermissionLinks import PermissionTechLink

    tech = session.exec(select(Technician).where(
        Technician.Email_Address == email)).first()
    if not tech:
        tech = Technician(Name=name, Email_Address=email,
                          Password=hash_password(seed_password()))
        tech.ID_Technician = generate_custom_id(
            session, Technician, "ID_Technician", "TEC")
        print(f"  + technician {email}")
    else:
        tech.Password = hash_password(seed_password())
    session.add(tech)
    session.commit()
    session.refresh(tech)
    # El técnico no tiene rol: política directa vía permission_tech
    if not session.get(PermissionTechLink, (policy.ID_Permission, tech.ID_Technician)):
        session.add(PermissionTechLink(
            permission_id=policy.ID_Permission, tech_id=tech.ID_Technician))
        session.commit()


def main() -> None:
    with get_session() as session:
        roles = {name: upsert_role(session, name) for name in ROLES}
        policies = {}
        for role_name, spec in ROLE_POLICIES.items():
            policies[role_name] = upsert_policy(session, roles[role_name], spec)

        # REG-098: los 4 roles del modelo llevan SOLO su política — despegar
        # cualquier permiso legacy colgado (p.ej. «Basic Subcontractor»).
        for role_name, role in roles.items():
            keep = policies[role_name].ID_Permission
            for link in session.exec(select(PermissionRoleLink).where(
                    PermissionRoleLink.role_id == role.ID_Role)).all():
                if link.permission_id != keep:
                    session.delete(link)
                    print(f"  - despegado permiso legacy {link.permission_id} de «{role_name}»")
        session.commit()
        for email, name, role_name in MEMBERS:
            upsert_member(session, email, name, roles[role_name])
        upsert_subcontractor(session, *SUBCONTRACTOR_USER, roles["Subcontractor"])
        upsert_technician(session, *TECHNICIAN_USER, policies["Technical"])
    print("✅ seed RBAC dev completado")


if __name__ == "__main__":
    main()
