"""Siembra los sujetos y el mundo que la auditoría de portal necesita.

Se ejecuta DESPUÉS de `scripts/seed_rbac.py`, del que reutiliza los upserts.
`seed_rbac.py` siembra usuarios, roles y políticas y nada más: ni un job, ni una
tarea, ni un enlace. Las corridas anteriores se apoyaban en los datos que ya
había en Neon develop; sobre una BD virgen hay que construir el mundo entero.

POR QUÉ HACEN FALTA MÁS SUJETOS
================================
La matriz del PR #116 tenía UN solo sujeto por rol. Con un solo sub es imposible
ver un IDOR entre pares: no hay «ajeno» contra el que probar. Aquí se siembran
dos subcontratistas sin nada en común y tres técnicos:

  sub_A  (sub-dev@)            ── técnico A (tech-dev@)      ── job A
  sub_B  (sub-b-dev@)          ── técnico B (tech-b-dev@)    ── job B
                                  técnico independiente (sin subcontratista)
                                                             ── job C (sin asignar)

Además ARREGLA UN DEFECTO DEL ARNÉS: `seed_rbac.py:242` nunca fija
`ID_Subcontractor`, así que `tech-dev` era un técnico INDEPENDIENTE. El sujeto
`technical` de toda la cobertura previa (matriz del PR #116, audit_tasks_matrix,
los 30 tests de Playwright) nunca colgó de un subcontratista, de modo que la
relación sub↔técnico —la que sostiene la regla R3— no la ha ejercitado nunca
ninguna prueba automática. Aquí `tech-dev` SÍ cuelga de `sub_A`, y el caso
independiente se cubre con un tercer técnico explícito.

VALORES CENTINELA
=================
Todo campo sensible lleva un valor RECONOCIBLE, nunca NULL. Si se dejara NULL,
una respuesta de portal sin datos financieros no probaría nada: no se podría
distinguir «el endpoint filtra el campo» de «la columna estaba vacía». Los
centinelas llevan el prefijo del propietario (`A-` o `B-`), así que al buscarlos
en una respuesta se sabe además DE QUIÉN es la fuga.

Uso:  .venv/bin/python scripts/seed_portal_audit.py [--limpiar]
Idempotente: se puede repetir. `--limpiar` borra solo lo que este script creó.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decouple import config  # noqa: E402

from src.utils.db_guard import require_dev_database  # noqa: E402

require_dev_database(config, contexto="seed_portal_audit")

from sqlmodel import select  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.AttachmentsModel import Attachments  # noqa: E402
from src.models.CertificateModel import Certificate  # noqa: E402
from src.models.ClientModel import Client  # noqa: E402
from src.models.ParentMgmtCoModel import ParentMgmtCo  # noqa: E402
from src.models.JobModel import Job  # noqa: E402
from src.models.OrderModel import Order  # noqa: E402
from src.models.PermissionModel import Permission  # noqa: E402
from src.models.RoleModel import Role  # noqa: E402
from src.models.SubcontractorModel import Subcontractor  # noqa: E402
from src.models.TasksModel import Tasks  # noqa: E402
from src.models.TechnicianModel import Technician  # noqa: E402
from src.models.TLActivityModel import TLActivity  # noqa: E402
from src.models.link_models.JobSubcontractor import JobSubcontractorLink  # noqa: E402
from src.models.link_models.JobTechnician import JobTechnicianLink  # noqa: E402
from src.utils.id_generator import generate_custom_id  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seed_rbac import upsert_subcontractor, upsert_technician  # noqa: E402

LIMPIAR = "--limpiar" in sys.argv
MARCA = "AUDIT-PORTAL"          # marca de todo lo que crea este script

SUB_B_EMAIL = "sub-b-dev@senavia-test.com"
TECH_B_EMAIL = "tech-b-dev@senavia-test.com"
TECH_INDEP_EMAIL = "tech-indep-dev@senavia-test.com"

HOY = date.today()


def _pol(session, nombre: str) -> Permission:
    p = session.exec(select(Permission).where(Permission.Name == nombre)).first()
    if not p:
        sys.exit(f"⛔ falta la política «{nombre}» — ejecuta antes scripts/seed_rbac.py")
    return p


def _rol(session, nombre: str) -> Role:
    r = session.exec(select(Role).where(Role.Name == nombre)).first()
    if not r:
        sys.exit(f"⛔ falta el rol «{nombre}» — ejecuta antes scripts/seed_rbac.py")
    return r



def _cliente(session, dueno: str) -> Client:
    """Cliente final + su empresa gestora (PMC).

    Dos motivos: (1) `tests/integration/test_portal_scoping.py:64` exige que
    exista un Client con ID_Community_Tracking o el módulo entero aborta; y (2)
    `/tlactivity/client/<id>` y `/tlactivity/parent-mgmt-co/<id>` no tienen
    scoping — sin un par propio/ajeno no hay contra qué probar la fuga.
    """
    nombre = f"{MARCA}-{dueno}-cliente"
    cli = session.exec(select(Client).where(Client.Client_Community == nombre)).first()
    if cli:
        return cli
    pmc = ParentMgmtCo(
        Property_mgmt_co=f"{MARCA}-{dueno}-gestora",
        Company_abbrev=f"{dueno}PMC",
        Main_office_email=f"{dueno.lower()}-gestora@example.invalid",
        Main_office_number="+1-555-0100",
        President_Name=f"{dueno}-PRESIDENTE-CONTACTO",
        President_Email=f"{dueno.lower()}-presidente@example.invalid",
        President_Phone="+1-555-0101",
        State="FL")
    pmc.ID_Community_Tracking = generate_custom_id(
        session, ParentMgmtCo, "ID_Community_Tracking", "PMC")
    session.add(pmc)
    session.commit()
    session.refresh(pmc)
    cli = Client(
        Client_Community=nombre,
        Address=f"{dueno}-CLIENTE-DIRECCION-PRIVADA",
        Email_Address=f"{dueno.lower()}-cliente@example.invalid",
        Phone_Number="+1-555-0102",
        Client_Status="Active",
        Text=f"{dueno}-NOTA-INTERNA-SOBRE-EL-CLIENTE",
        ID_Community_Tracking=pmc.ID_Community_Tracking)
    cli.ID_Client = generate_custom_id(session, Client, "ID_Client", "CLI")
    session.add(cli)
    session.commit()
    session.refresh(cli)
    print(f"  + cliente {cli.ID_Client} «{nombre}» bajo gestora {pmc.ID_Community_Tracking}")
    return cli


def _job(session, dueno: str, cliente: Client, nombre: str, tipo: str = "QID") -> Job:
    """Job con TODOS los campos sensibles poblados con centinelas de `dueno`."""
    job = session.exec(select(Job).where(Job.Project_name == nombre)).first()
    if job:
        return job
    job = Job(
        Job_type=tipo,
        Project_name=nombre,
        Project_location=f"{dueno}-DIRECCION-CALLE-FALSA-123",
        Job_status="Work-in-progress",
        Service_type="Restoration",
        Po_wtn_wo=f"{dueno}-PO-0001",
        Date_assigned=HOY - timedelta(days=30),
        Estimated_start_date=HOY - timedelta(days=20),
        Estimated_completion_date=HOY + timedelta(days=20),
        Estimated_project_duration="40 days",
        Additional_detail=f"{dueno}-NOTA-INTERNA-GQM",
        # ── bloque financiero: lo que un rol de portal NO debería ver ──
        Estimated_rent=1111.11,
        Estimated_material=2222.22,
        Tech_formula_pricing=3333.33,
        Gqm_formula_pricing=4444.44,
        Gqm_adj_formula_pricing=5555.55,
        Gqm_target_sold_pricing=6666.66,
        Gqm_target_return=7777.77,
        Gqm_premium_in_money=8888.88,
        Gqm_final_sold_pricing=9999.99,
        Gqm_final_percentage=42.0,
        Gqm_total_change_orders=1212.12,
        Gqm_total_materials_fees=1313.13,
        Acc_receivable=1414.14,
        Gqm_final_target_return=1515.15,
        Gqm_paid_fees=1616.16,
        Bldg_dept_fees=1717.17,
        Ptl_gc_fee=1818.18,
        ID_Client=cliente.ID_Client,
        podio_item_id=None,
        podio_app_year=HOY.year,
    )
    job.ID_Jobs = generate_custom_id(session, Job, "ID_Jobs", f"{tipo}-I")
    session.add(job)
    session.commit()
    session.refresh(job)
    print(f"  + job {job.ID_Jobs} «{nombre}»")
    return job


def _tarea(session, nombre, job=None, tech=None, sub=None, estado="Not started"):
    t = session.exec(select(Tasks).where(Tasks.Name == nombre)).first()
    if t:
        return t
    t = Tasks(
        Name=nombre,
        Task_description=f"{nombre} — descripción",
        Task_status=estado,
        Priority="Medium",
        Designation_date=HOY,
        Delivery_date=HOY + timedelta(days=7),
        ID_Jobs=job.ID_Jobs if job else None,
        ID_Technician=tech.ID_Technician if tech else None,
        ID_Subcontractor=sub.ID_Subcontractor if sub else None,
    )
    t.ID_Tasks = generate_custom_id(session, Tasks, "ID_Tasks", "TSK")
    session.add(t)
    session.commit()
    session.refresh(t)
    print(f"  + tarea {t.ID_Tasks} «{nombre}»")
    return t


def _enlazar(session, job, sub=None, tech=None):
    if sub and not session.get(JobSubcontractorLink, (job.ID_Jobs, sub.ID_Subcontractor)):
        session.add(JobSubcontractorLink(job_id=job.ID_Jobs, subcontr_id=sub.ID_Subcontractor))
    if tech and not session.get(JobTechnicianLink, (job.ID_Jobs, tech.ID_Technician)):
        session.add(JobTechnicianLink(job_id=job.ID_Jobs, technician_id=tech.ID_Technician))
    session.commit()


def _adjunto(session, nombre, job=None, sub=None, tech=None, nivel="internal"):
    a = session.exec(select(Attachments).where(Attachments.Document_name == nombre)).first()
    if a:
        return a
    a = Attachments(
        Document_name=nombre,
        Attachment_descr=f"{nombre} — adjunto de auditoría",
        Link=f"https://example.invalid/{nombre}",
        Document_type="pdf",
        access_level=nivel,
        ID_Jobs=job.ID_Jobs if job else None,
        ID_Subcontractor=sub.ID_Subcontractor if sub else None,
        ID_Technician=tech.ID_Technician if tech else None,
    )
    a.ID_Attachment = generate_custom_id(session, Attachments, "ID_Attachment", "ATT")
    session.add(a)
    session.commit()
    session.refresh(a)
    print(f"  + adjunto {a.ID_Attachment} «{nombre}» (access_level={nivel})")
    return a


def _certificado(session, nombre, sub):
    c = session.exec(select(Certificate).where(Certificate.Name == nombre)).first()
    if c:
        return c
    c = Certificate(Name=nombre, Status="Active", Expiration_date=HOY + timedelta(days=365),
                    Notes=f"{nombre} — nota de cumplimiento",
                    ID_Subcontractor=sub.ID_Subcontractor)
    c.ID_Certificate = generate_custom_id(session, Certificate, "ID_Certificate", "CERT")
    session.add(c)
    session.commit()
    session.refresh(c)
    print(f"  + certificado {c.ID_Certificate} «{nombre}»")
    return c


def _tlactivity(session, descripcion, job=None, sub=None, tech=None):
    a = session.exec(select(TLActivity).where(TLActivity.Description == descripcion)).first()
    if a:
        return a
    a = TLActivity(Action="audit_seed", Action_datetime=datetime.utcnow(),
                   Description=descripcion,
                   ID_Jobs=job.ID_Jobs if job else None,
                   ID_Subcontractor=sub.ID_Subcontractor if sub else None,
                   ID_Technician=tech.ID_Technician if tech else None)
    a.ID_TLActivity = generate_custom_id(session, TLActivity, "ID_TLActivity", "TLA")
    session.add(a)
    session.commit()
    session.refresh(a)
    print(f"  + tlactivity {a.ID_TLActivity}")
    return a


def _tlactivity_cliente(session, descripcion, cliente):
    a = session.exec(select(TLActivity).where(TLActivity.Description == descripcion)).first()
    if a:
        return a
    a = TLActivity(Action="audit_seed", Action_datetime=datetime.utcnow(),
                   Description=descripcion, ID_Client=cliente.ID_Client,
                   ID_Community_Tracking=cliente.ID_Community_Tracking)
    a.ID_TLActivity = generate_custom_id(session, TLActivity, "ID_TLActivity", "TLA")
    session.add(a)
    session.commit()
    session.refresh(a)
    print(f"  + tlactivity {a.ID_TLActivity} (cliente {cliente.ID_Client})")
    return a


def _orden(session, titulo, sub):
    o = session.exec(select(Order).where(Order.Title == titulo)).first()
    if o:
        return o
    o = Order(Title=titulo, Formula=2500.50, Adj_formula=2600.75,
              Notes=f"{titulo} — condiciones económicas del subcontratista",
              Payment_1=800.00, Payment_2=900.00, Payment_3=900.50,
              ID_Subcontractor=sub.ID_Subcontractor)
    o.ID_Order = generate_custom_id(session, Order, "ID_Order", "ORD")
    session.add(o)
    session.commit()
    session.refresh(o)
    print(f"  + orden {o.ID_Order} «{titulo}»")
    return o


def limpiar(session) -> None:
    """Borra SOLO lo que este script crea. No toca lo de seed_rbac.py."""
    borrados = 0
    for modelo, campo in ((Tasks, "Name"), (Attachments, "Document_name"),
                          (Certificate, "Name"), (Order, "Title")):
        for fila in session.exec(select(modelo).where(
                getattr(modelo, campo).like(f"%{MARCA}%"))).all():
            session.delete(fila); borrados += 1
    for fila in session.exec(select(TLActivity).where(
            TLActivity.Description.like(f"%{MARCA}%"))).all():
        session.delete(fila); borrados += 1
    session.commit()
    for job in session.exec(select(Job).where(Job.Project_name.like(f"%{MARCA}%"))).all():
        for enlace in session.exec(select(JobSubcontractorLink).where(
                JobSubcontractorLink.job_id == job.ID_Jobs)).all():
            session.delete(enlace); borrados += 1
        for enlace in session.exec(select(JobTechnicianLink).where(
                JobTechnicianLink.job_id == job.ID_Jobs)).all():
            session.delete(enlace); borrados += 1
        session.delete(job); borrados += 1
    session.commit()
    for cli in session.exec(select(Client).where(
            Client.Client_Community.like(f"%{MARCA}%"))).all():
        session.delete(cli); borrados += 1
    session.commit()
    for pmc in session.exec(select(ParentMgmtCo).where(
            ParentMgmtCo.Property_mgmt_co.like(f"%{MARCA}%"))).all():
        session.delete(pmc); borrados += 1
    session.commit()
    for email in (TECH_B_EMAIL, TECH_INDEP_EMAIL):
        t = session.exec(select(Technician).where(Technician.Email_Address == email)).first()
        if t:
            session.delete(t); borrados += 1
    s = session.exec(select(Subcontractor).where(
        Subcontractor.Email_Address == SUB_B_EMAIL)).first()
    if s:
        session.delete(s); borrados += 1
    session.commit()
    print(f"🧹 limpiadas {borrados} filas de «{MARCA}»")


def main() -> None:
    with get_session() as session:
        if LIMPIAR:
            limpiar(session)
            return

        rol_sub = _rol(session, "Subcontractor")
        pol_tech = _pol(session, "technical-portal")

        # ── Sujetos ───────────────────────────────────────────────────────────
        upsert_subcontractor(session, SUB_B_EMAIL, "DEV Subcontractor B", rol_sub)
        upsert_technician(session, TECH_B_EMAIL, "DEV Technician de B", pol_tech)
        upsert_technician(session, TECH_INDEP_EMAIL, "DEV Technician independiente", pol_tech)

        sub_a = session.exec(select(Subcontractor).where(
            Subcontractor.Email_Address == "sub-dev@senavia-test.com")).first()
        sub_b = session.exec(select(Subcontractor).where(
            Subcontractor.Email_Address == SUB_B_EMAIL)).first()
        tech_a = session.exec(select(Technician).where(
            Technician.Email_Address == "tech-dev@senavia-test.com")).first()
        tech_b = session.exec(select(Technician).where(
            Technician.Email_Address == TECH_B_EMAIL)).first()
        tech_i = session.exec(select(Technician).where(
            Technician.Email_Address == TECH_INDEP_EMAIL)).first()
        if not all((sub_a, sub_b, tech_a, tech_b, tech_i)):
            sys.exit("⛔ faltan sujetos — ejecuta antes scripts/seed_rbac.py")

        # Colgar cada técnico de su sub. tech_a lo necesita porque seed_rbac.py
        # nunca fijó ID_Subcontractor (ver cabecera).
        for tech, sub, etiqueta in ((tech_a, sub_a, "A"), (tech_b, sub_b, "B")):
            if tech.ID_Subcontractor != sub.ID_Subcontractor:
                tech.ID_Subcontractor = sub.ID_Subcontractor
                session.add(tech)
                print(f"  ~ técnico {tech.ID_Technician} colgado de {sub.ID_Subcontractor} ({etiqueta})")
        if tech_i.ID_Subcontractor is not None:
            tech_i.ID_Subcontractor = None
            session.add(tech_i)
        session.commit()

        # ── Mundo A (sub_a) ───────────────────────────────────────────────────
        cli_a = _cliente(session, "A")
        job_a = _job(session, "A", cli_a, f"{MARCA}-A-job-de-sub-A")
        _enlazar(session, job_a, sub=sub_a, tech=tech_a)
        t_a1 = _tarea(session, f"{MARCA}-A-tarea-de-tech-A", job_a, tech=tech_a, sub=sub_a)
        t_a2 = _tarea(session, f"{MARCA}-A-tarea-sin-asignar", job_a, sub=sub_a)
        _adjunto(session, f"{MARCA}-A-adjunto-job", job=job_a, nivel="internal")
        _adjunto(session, f"{MARCA}-A-adjunto-tecnico", tech=tech_a, nivel="technicians")
        _certificado(session, f"{MARCA}-A-certificado", sub_a)
        _tlactivity(session, f"{MARCA}-A-evento-timeline", job=job_a, sub=sub_a)
        _orden(session, f"{MARCA}-A-orden", sub_a)
        _tlactivity_cliente(session, f"{MARCA}-A-evento-cliente", cli_a)

        # ── Mundo B (sub_b) — sin NADA en común con A ─────────────────────────
        cli_b = _cliente(session, "B")
        job_b = _job(session, "B", cli_b, f"{MARCA}-B-job-de-sub-B", tipo="PTL")
        _enlazar(session, job_b, sub=sub_b, tech=tech_b)
        t_b1 = _tarea(session, f"{MARCA}-B-tarea-de-tech-B", job_b, tech=tech_b, sub=sub_b)
        _adjunto(session, f"{MARCA}-B-adjunto-job", job=job_b, nivel="internal")
        _adjunto(session, f"{MARCA}-B-adjunto-tecnico", tech=tech_b, nivel="technicians")
        _certificado(session, f"{MARCA}-B-certificado", sub_b)
        _tlactivity(session, f"{MARCA}-B-evento-timeline", job=job_b, sub=sub_b)
        _orden(session, f"{MARCA}-B-orden", sub_b)
        _tlactivity_cliente(session, f"{MARCA}-B-evento-cliente", cli_b)

        # ── Mundo D — job COMPARTIDO entre sub A y sub B ──────────────────────
        # Sin este fixture, el caso «dos subcontratistas en la misma obra» es
        # invisible para el arnés: con A y B en mundos disjuntos, la matriz solo
        # puede ver el IDOR por id, no la fuga POR LA COLECCIÓN ANIDADA. Y ahí
        # estaba: `GET /jobs/<compartido>` le entregaba a sub A la ficha de
        # sub_B y su orden ORD60002 dentro de `subcontractors[].orders[]`.
        cli_d = _cliente(session, "D")
        job_d = _job(session, "D", cli_d, f"{MARCA}-D-job-compartido-A-y-B")
        _enlazar(session, job_d, sub=sub_a, tech=tech_a)
        _enlazar(session, job_d, sub=sub_b, tech=tech_b)
        _tarea(session, f"{MARCA}-D-tarea-de-A", job_d, tech=tech_a, sub=sub_a)
        _tarea(session, f"{MARCA}-D-tarea-de-B", job_d, tech=tech_b, sub=sub_b)

        # ── Mundo C — job sin asignar y técnico independiente ─────────────────
        cli_c = _cliente(session, "C")
        job_c = _job(session, "C", cli_c, f"{MARCA}-C-job-sin-asignar", tipo="PAR")
        t_c1 = _tarea(session, f"{MARCA}-C-tarea-huerfana", job_c)
        t_i1 = _tarea(session, f"{MARCA}-I-tarea-de-tech-independiente", job_c, tech=tech_i)
        _enlazar(session, job_c, tech=tech_i)

        # ── Inventario para 00-entorno.md ─────────────────────────────────────
        print("\n" + "=" * 72)
        print("SUJETOS Y OBJETOS SEMBRADOS — IDs reales")
        print("=" * 72)
        filas = [
            ("subcontractor", "sub-dev@senavia-test.com", sub_a.ID_Subcontractor, "sub A"),
            ("sub_B", SUB_B_EMAIL, sub_b.ID_Subcontractor, "sub B — ningún job en común"),
            ("technical", "tech-dev@senavia-test.com", tech_a.ID_Technician,
             f"bajo {sub_a.ID_Subcontractor}"),
            ("tech_de_sub_B", TECH_B_EMAIL, tech_b.ID_Technician, f"bajo {sub_b.ID_Subcontractor}"),
            ("tech_independiente", TECH_INDEP_EMAIL, tech_i.ID_Technician, "SIN subcontratista"),
            ("job propio de A", "—", job_a.ID_Jobs, f"sub={sub_a.ID_Subcontractor} tech={tech_a.ID_Technician}"),
            ("job propio de B", "—", job_b.ID_Jobs, f"sub={sub_b.ID_Subcontractor} tech={tech_b.ID_Technician}"),
            ("job sin asignar", "—", job_c.ID_Jobs, f"solo tech independiente {tech_i.ID_Technician}"),
            ("job COMPARTIDO A+B", "—", job_d.ID_Jobs, "misma obra, dos subcontratistas"),
            ("tarea de tech A", "—", t_a1.ID_Tasks, "propia de A"),
            ("tarea sin asignar de A", "—", t_a2.ID_Tasks, "job A, sin técnico"),
            ("tarea de tech B", "—", t_b1.ID_Tasks, "propia de B — «ajena» para A"),
            ("tarea huérfana", "—", t_c1.ID_Tasks, "job C, sin técnico ni sub"),
            ("tarea de tech indep.", "—", t_i1.ID_Tasks, "job C"),
        ]
        for rol, email, ident, nota in filas:
            print(f"  {rol:24s} {email:32s} {ident:14s} {nota}")
        print("=" * 72)
        print("\nCentinelas financieros en cada job (para la Fase 4):")
        print("  Gqm_formula_pricing=4444.44  Gqm_target_return=7777.77")
        print("  Gqm_final_sold_pricing=9999.99  Acc_receivable=1414.14")
        print("  Project_location='<A|B|C>-DIRECCION-CALLE-FALSA-123'")
        print("  Additional_detail='<A|B|C>-NOTA-INTERNA-GQM'")
    print("\n✅ siembra de auditoría de portal completada")


if __name__ == "__main__":
    main()
