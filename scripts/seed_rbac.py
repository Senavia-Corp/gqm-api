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

# Documentos de política por rol. Se completan en el Bloque 2 (RBAC):
# GQM Member / Subcontractor / Technical reciben aquí sus documentos definitivos.
ROLE_POLICIES = {
    "Full Admin": {
        "Name": "full-admin-all",
        "Description": "Acceso total",
        "Document": {"Statement": [{"Effect": "Allow", "Action": ["*"], "Resource": ["*"]}]},
    },
}

# (email, nombre, rol) — usuarios Member de prueba; sub/tech se siembran en B2.
MEMBERS = [
    ("admin-dev@senavia-test.com", "DEV Admin", "Full Admin"),
]


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


def main() -> None:
    with get_session() as session:
        roles = {name: upsert_role(session, name) for name in ROLES}
        for role_name, spec in ROLE_POLICIES.items():
            upsert_policy(session, roles[role_name], spec)
        for email, name, role_name in MEMBERS:
            upsert_member(session, email, name, roles[role_name])
    print("✅ seed RBAC dev completado")


if __name__ == "__main__":
    main()
