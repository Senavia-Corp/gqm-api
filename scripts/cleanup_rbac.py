"""Limpieza RBAC al modelo de 4 roles (complemento de seed_rbac.py).

Deja el sistema SOLO con los 4 roles y sus 4 políticas:
  0. Comprobaciones previas: tablas, roles y que TODOS los members tengan
     rol objetivo confirmado. Si algo falla, aborta SIN tocar nada.
  1. Asigna rol a cada Member según el mapeo CONFIRMADO por Manuel
     (spec IAM v3.0, tabla del 11-jun-2026) — por email.
  1b. Backfill del portal: subcontractors → rol Subcontractor y technicians
     → política technical-portal (sin esto el portal queda sin permisos).
  2. Desenlaza los permisos legacy de roles/members/techs/subs
     (incluye inline peligrosos tipo «Full Admin IAM» directo a un member).
  3. Borra los permisos legacy (todo lo que no sea una de las 4 políticas).
  4. Borra los roles legacy y fantasma (sin nombre, inactivos, vacíos).

Idempotente: re-ejecutarlo no cambia nada si ya está limpio.
Guardas: aborta salvo Neon develop + APP_ENV=test (igual que el seed);
para el cutover, revisar el mapeo y relajar la guarda CONSCIENTEMENTE.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decouple import config  # noqa: E402

# Producción exige el flag EXPLÍCITO --produccion (el cutover). Sin él, solo
# corre contra Neon develop. Antes había que editar estas guardas a mano el
# día del cutover, que es justo cuando no se deben tocar guardas.
PRODUCCION = "--produccion" in sys.argv

if not PRODUCCION:
    if "ep-sparkling-sound" not in config("DATABASE_URL", default=""):
        sys.exit("⛔ DATABASE_URL no apunta a Neon develop — abortado "
                 "(para el cutover: --produccion, tras leer RUNBOOK-CUTOVER.md)")
    if config("APP_ENV", default="") != "test":
        sys.exit("⛔ APP_ENV != test — abortado "
                 "(para el cutover: --produccion, tras leer RUNBOOK-CUTOVER.md)")

from sqlmodel import select  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.MemberModel import Member  # noqa: E402
from src.models.PermissionModel import Permission  # noqa: E402
from src.models.RoleModel import Role  # noqa: E402
from src.models.SubcontractorModel import Subcontractor  # noqa: E402
from src.models.link_models.PermissionLinks import (  # noqa: E402
    PermissionMemberLink,
    PermissionRoleLink,
    PermissionSubcLink,
    PermissionTechLink,
)

MANAGED_ROLES = {"Full Admin", "GQM Member", "Subcontractor", "Technical"}
MANAGED_PERMISSIONS = {
    "full-admin-all", "gqm-member-operativo",
    "subcontractor-portal", "technical-portal",
}

# Mapeo confirmado (spec IAM v3.0 — validado con Manuel 11-jun-2026).
# Se incluyen las dos variantes de email de Manuel vistas en prod/spec.
FULL_ADMIN_EMAILS = {
    "manuel@gqmservice.com", "mramirez@gqmservice.com",   # Manuel Ramirez
    "jthornton@gqmservice.com",                            # Jagger Thornton
    "avillamizar@gqmservice.com",                          # Allison Villamizar
    "sebastian@senaviacorp.com",                           # Técnico SENAVIA
    "jeferson@senaviacorp.com",                            # Técnico SENAVIA
    "admin-dev@senavia-test.com",                          # seed dev
}
# Cuentas que NO deben recibir rol: quedan con CERO políticas a propósito.
# Sin esta lista, el preflight abortaba por MEM60011 y la «solución» obvia
# —añadirlo a los mapeos— le habría CONCEDIDO acceso al insider.
EXCLUIDOS_SIN_ROL = {
    "juan-block@senaviacorp.com",   # MEM60011 — cuenta insider, desactivada
    "juanjj272001@gmail.com",       # TEC60001 — technician ligado al insider
}
GQM_MEMBER_EMAILS = {
    "sreed@gqmservice.com", "kramirez@gqmservice.com",
    "pcolman@gqmservice.com", "flopez@gqmservice.com",
    "mvargas@gqmservice.com", "jbabilonia@gqmservice.com",
    "abaena@gqmservice.com",
    "aielet@senaviacorp.com",  # equipo SENAVIA, operativo
    "member-dev@senavia-test.com",  # seed dev
}


def preflight(s) -> dict:
    """TODO lo que puede abortar, ANTES de borrar nada: si un member se
    quedaría sin rol, o falta una tabla/rol, se sale sin tocar la BD (antes
    el script borraba los permisos legacy y luego avisaba: el usuario sin
    mapeo quedaba con un rol cascarón y sin permisos, y salía con código 0)."""
    from sqlalchemy import inspect as sa_inspect

    problemas = []

    tablas = set(sa_inspect(s.get_bind()).get_table_names())
    for t in ("permission_role", "permission_member", "permission_tech",
              "permission_subc"):
        if t not in tablas:
            problemas.append(f"falta la tabla {t} — corre antes «alembic upgrade head»")

    roles = {r.Name: r for r in s.exec(select(Role)).all() if r.Name}
    faltan = MANAGED_ROLES - roles.keys()
    if faltan:
        problemas.append(f"faltan roles gestionados {sorted(faltan)} — corre antes "
                         "«seed_rbac.py --roles-only»")

    sin_mapeo = [
        f"{m.ID_Member} <{m.Email_Address}>"
        for m in s.exec(select(Member)).all()
        if (m.Email_Address or "").strip().lower() not in FULL_ADMIN_EMAILS
        and (m.Email_Address or "").strip().lower() not in GQM_MEMBER_EMAILS
        and (m.Email_Address or "").strip().lower() not in EXCLUIDOS_SIN_ROL
    ]
    if sin_mapeo:
        problemas.append(
            "members sin rol objetivo confirmado (se quedarían SIN permisos): "
            + ", ".join(sin_mapeo)
            + " — añádelos a FULL_ADMIN_EMAILS/GQM_MEMBER_EMAILS y repite")

    if problemas:
        print("⛔ comprobaciones previas fallidas — no se tocó nada:")
        for p in problemas:
            print(f"   · {p}")
        sys.exit(1)

    print("✅ comprobaciones previas OK")
    return roles


def backfill_portal(s, roles) -> None:
    """Sin esto, tras el cutover TODO el portal queda muerto: los subs reales
    no tienen ID_Role y los técnicos pierden su permiso legacy, así que el
    login les devuelve políticas vacías (hallazgo ALTO de la auditoría)."""
    from src.models.PermissionModel import Permission
    from src.models.TechnicianModel import Technician

    sub_role = roles["Subcontractor"]
    n = 0
    for sub in s.exec(select(Subcontractor)).all():
        if sub.ID_Role != sub_role.ID_Role:
            sub.ID_Role = sub_role.ID_Role
            s.add(sub)
            n += 1
    print(f"  · {n} subcontractors enlazados al rol «Subcontractor»")

    tech_policy = s.exec(select(Permission).where(
        Permission.Name == "technical-portal")).first()
    if not tech_policy:
        sys.exit("⛔ falta la política technical-portal — corre seed_rbac.py --roles-only")
    n = 0
    for tech in s.exec(select(Technician)).all():
        if (getattr(tech, "Email_Address", "") or "").strip().lower() in EXCLUIDOS_SIN_ROL:
            print(f"  ⛔ excluido del portal: {tech.ID_Technician}")
            continue
        if not s.get(PermissionTechLink,
                     (tech_policy.ID_Permission, tech.ID_Technician)):
            s.add(PermissionTechLink(permission_id=tech_policy.ID_Permission,
                                     tech_id=tech.ID_Technician))
            n += 1
    print(f"  · {n} technicians enlazados a «technical-portal»")
    s.commit()


def main() -> None:
    with get_session() as s:
        roles = preflight(s)
        full_admin = roles["Full Admin"]
        gqm_member = roles["GQM Member"]

        # ── 1. Asignación de roles por email confirmado ──────────────────
        for m in s.exec(select(Member)).all():
            email = (m.Email_Address or "").strip().lower()
            if email in EXCLUIDOS_SIN_ROL:
                if m.ID_Role is not None:
                    print(f"  ⛔ excluida: {m.ID_Member} {email} → sin rol")
                    m.ID_Role = None
                    s.add(m)
                continue
            target = full_admin if email in FULL_ADMIN_EMAILS else gqm_member
            if m.ID_Role != target.ID_Role:
                print(f"  rol → {target.Name}: {m.ID_Member} {email}")
                m.ID_Role = target.ID_Role
                s.add(m)
        s.commit()

        # ── 1b. Portal: subs y técnicos ──────────────────────────────────
        backfill_portal(s, roles)

        # ── 2-3. Permisos legacy: desenlazar y borrar ────────────────────
        legacy_perms = [p for p in s.exec(select(Permission)).all()
                        if p.Name not in MANAGED_PERMISSIONS]
        for p in legacy_perms:
            for link_model, col in (
                (PermissionRoleLink, PermissionRoleLink.permission_id),
                (PermissionMemberLink, PermissionMemberLink.permission_id),
                (PermissionTechLink, PermissionTechLink.permission_id),
                (PermissionSubcLink, PermissionSubcLink.permission_id),
            ):
                for link in s.exec(select(link_model).where(col == p.ID_Permission)).all():
                    s.delete(link)
            print(f"  🗑️ permiso legacy: {p.ID_Permission} {p.Name!r}")
            s.delete(p)
        s.commit()

        # ── 4. Roles legacy/fantasma ─────────────────────────────────────
        for r in s.exec(select(Role)).all():
            if r.Name in MANAGED_ROLES:
                continue
            holders = s.exec(select(Member).where(Member.ID_Role == r.ID_Role)).all()
            holders += s.exec(select(Subcontractor).where(
                Subcontractor.ID_Role == r.ID_Role)).all()
            if holders:
                # No debería pasar tras el paso 1 — nunca dejar usuarios colgando
                print(f"  ⚠️ {r.ID_Role} {r.Name!r} tiene usuarios sin mapeo "
                      f"({[getattr(h, 'ID_Member', None) or h.ID_Subcontractor for h in holders]}) — NO se borra")
                continue
            for link in s.exec(select(PermissionRoleLink).where(
                    PermissionRoleLink.role_id == r.ID_Role)).all():
                s.delete(link)
            print(f"  🗑️ rol legacy/fantasma: {r.ID_Role} {r.Name!r}")
            s.delete(r)
        s.commit()

        # ── Resumen ──────────────────────────────────────────────────────
        roles_left = s.exec(select(Role)).all()
        perms_left = s.exec(select(Permission)).all()
        print(f"\n✅ limpieza completada — quedan {len(roles_left)} roles "
              f"{sorted(r.Name for r in roles_left)} y {len(perms_left)} permisos "
              f"{sorted(p.Name for p in perms_left)}")


if __name__ == "__main__":
    main()
