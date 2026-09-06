"""Flujo end-to-end del portal, con la PRUEBA NEGATIVA de cada paso.

El recorrido completo del negocio: admin crea job -> lo asigna al sub -> el sub
lo ve -> crea tarea para SU tecnico -> el tecnico la ve y la actualiza -> sub y
admin ven el cambio -> admin cierra el job.

Lo que lo hace una prueba y no una demo: en cada paso se comprueba tambien QUIEN
NO DEBIA VERLO. `sub_B` y `tech_de_sub_B` no comparten ningun job con el mundo A,
asi que cualquier 200 suyo es una fuga. Y cada escritura se verifica RELEYENDO LA
FILA: la respuesta HTTP no es prueba de escritura (T-07: `POST /tasks/ {}`
devolvia 201 con todo NULL).

Sale != 0 si algun paso o alguna negativa falla. Limpia lo que crea.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import select  # noqa: E402

from scripts.audit_portal_lib import call, fila_bd, ids_de, tokens  # noqa: E402
from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.JobModel import Job  # noqa: E402
from src.models.TasksModel import Tasks  # noqa: E402
from src.models.link_models.JobSubcontractor import JobSubcontractorLink  # noqa: E402

FALLOS = []


def comprueba(condicion, descripcion):
    print(f"  {'✔' if condicion else '❌'} {descripcion}")
    if not condicion:
        FALLOS.append(descripcion)


def main() -> int:
    T = tokens()
    ADM, SUB, TEC = T["full_admin"], T["subcontractor"], T["technical"]
    SUBB, TECB = T["sub_B"], T["tech_de_sub_B"]
    job = tid = None
    try:
        print("1 · admin crea un job")
        st, pl = call(ADM, "POST", "/jobs/", {
            "Job_type": "QID", "Project_name": "AUDIT-E2E-job",
            "Job_status": "Not started", "Project_location": "E2E-DIRECCION"})
        job = pl.get("ID_Jobs") if isinstance(pl, dict) else None
        comprueba(st == 201 and job and fila_bd(Job, job) is not None,
                  f"HTTP {st}, y la fila {job} existe en BD")

        print("2 · admin lo asigna al sub")
        st, _ = call(ADM, "POST", f"/job_subcontractor/jobs/{job}/subcontractors/SUBC60001")
        with get_session() as s:
            enlazado = s.get(JobSubcontractorLink, (job, "SUBC60001")) is not None
        comprueba(st in (200, 201) and enlazado, f"HTTP {st}, y el enlace existe en BD")

        print("3 · el sub lo ve · NEGATIVA: sub_B no")
        st_a, _ = call(SUB, "GET", f"/jobs/{job}")
        st_b, _ = call(SUBB, "GET", f"/jobs/{job}")
        comprueba(st_a == 200, f"el sub asignado lo ve ({st_a})")
        comprueba(st_b == 404, f"sub_B NO lo ve ({st_b}, esperado 404)")

        print("4 · el sub crea una tarea para SU tecnico")
        st, pl = call(SUB, "POST", "/tasks/", {
            "Name": "AUDIT-E2E-tarea", "ID_Jobs": job, "ID_Subcontractor": "SUBC60001",
            "ID_Technician": "TEC60001", "Task_status": "Not started", "Priority": "High"})
        tid = pl.get("ID_Tasks") if isinstance(pl, dict) else None
        fila = fila_bd(Tasks, tid) if tid else None
        comprueba(st == 201 and fila is not None and fila.ID_Technician == "TEC60001",
                  f"HTTP {st}, y en BD ID_Technician={getattr(fila, 'ID_Technician', None)}")

        print("5 · el tecnico ve su tarea · NEGATIVA: tech_de_sub_B no")
        va = ids_de(call(TEC, "GET", "/tasks/?limit=100")[1], "ID_Tasks")
        vb = ids_de(call(TECB, "GET", "/tasks/?limit=100")[1], "ID_Tasks")
        comprueba(tid in va, f"el tecnico asignado la ve ({sorted(va)})")
        comprueba(tid not in vb, f"el tecnico del otro sub NO la ve ({sorted(vb)})")

        print("6 · el tecnico actualiza el estado")
        st, _ = call(TEC, "PATCH", f"/tasks/{tid}", {"Task_status": "Work-in-progress"})
        fila = fila_bd(Tasks, tid)
        comprueba(st == 200 and fila.Task_status == "Work-in-progress",
                  f"HTTP {st}, y en BD Task_status={fila.Task_status!r}")

        print("7 · sub y admin ven el cambio · NEGATIVA: sub_B sigue sin verlo")
        _, pa = call(SUB, "GET", f"/tasks/{tid}")
        _, pm = call(ADM, "GET", f"/tasks/{tid}")
        st_b, _ = call(SUBB, "GET", f"/tasks/{tid}")
        comprueba(isinstance(pa, dict) and pa.get("Task_status") == "Work-in-progress",
                  "el sub ve el estado nuevo")
        comprueba(isinstance(pm, dict) and pm.get("Task_status") == "Work-in-progress",
                  "el admin ve el estado nuevo")
        comprueba(st_b == 404, f"sub_B NO ve la tarea ({st_b}, esperado 404)")

        print("8 · admin cierra el job")
        st, _ = call(ADM, "PATCH", f"/jobs/{job}", {"Job_status": "Completed"})
        with get_session() as s:
            cerrado = s.get(Job, job).Job_status
        comprueba(st == 200 and cerrado == "Completed", f"HTTP {st}, y en BD {cerrado!r}")

    finally:
        with get_session() as s:
            for t in s.exec(select(Tasks).where(Tasks.Name.like("AUDIT-E2E%"))).all():
                s.delete(t)
            if job:
                for l in s.exec(select(JobSubcontractorLink).where(
                        JobSubcontractorLink.job_id == job)).all():
                    s.delete(l)
            s.commit()
            if job and s.get(Job, job):
                s.delete(s.get(Job, job)); s.commit()

    print()
    if FALLOS:
        print(f"❌ {len(FALLOS)} comprobacion(es) fallan:")
        for f in FALLOS:
            print(f"   · {f}")
        return 1
    print("✅ flujo completo y las 3 pruebas negativas pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
