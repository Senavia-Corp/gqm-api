"""Saneamiento de la tabla `tasks` — idempotente y con DRY-RUN por defecto.

Arregla SOLO lo que tiene una correspondencia inequívoca (el vocabulario de
estados). Todo lo demás se REPORTA, porque corregirlo exigiría adivinar la
intención de quien lo escribió — y adivinar datos es peor que dejarlos sucios.

Uso:
    .venv/bin/python scripts/sanear_tasks.py              # dry-run (no escribe)
    .venv/bin/python scripts/sanear_tasks.py --aplicar    # escribe
    .venv/bin/python scripts/sanear_tasks.py --permitir-produccion --aplicar

Sin `--permitir-produccion` aborta si la BD no es Neon develop.
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from decouple import config  # noqa: E402
from sqlmodel import select  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.TasksModel import Tasks  # noqa: E402

APLICAR = "--aplicar" in sys.argv
PROD_OK = "--permitir-produccion" in sys.argv

DB = config("DATABASE_URL", default="")
if "ep-sparkling-sound" not in DB and not PROD_OK:
    sys.exit("⛔ La BD no es Neon develop. Usa --permitir-produccion si es intencional.")
if PROD_OK and APLICAR:
    print("⚠️  MODO PRODUCCIÓN CON ESCRITURA. Ctrl-C en 5 s para abortar.")
    import time
    time.sleep(5)

# Correspondencia inequívoca: mismo significado, distinta capitalización/redacción.
MAPA_ESTADO = {
    "Not Started": "Not started",
    "not started": "Not started",
    "In Progress": "Work-in-progress",
    "in progress": "Work-in-progress",
    "Work in progress": "Work-in-progress",
    "completed": "Completed",
}
CANON_ESTADO = {"Not started", "Work-in-progress", "Completed"}
CANON_PRIO = {"High", "Medium", "Low"}


def main():
    arreglos, avisos = [], []
    with get_session() as s:
        filas = s.exec(select(Tasks)).all()

        for r in filas:
            # ── ARREGLABLE: vocabulario de estado ────────────────────────────
            if r.Task_status and r.Task_status not in CANON_ESTADO:
                nuevo = MAPA_ESTADO.get(r.Task_status)
                if nuevo:
                    arreglos.append((r.ID_Tasks, "Task_status", r.Task_status, nuevo))
                    if APLICAR:
                        r.Task_status = nuevo
                else:
                    avisos.append((r.ID_Tasks, "estado desconocido",
                                   f"{r.Task_status!r} — sin correspondencia, no se toca"))

            # ── SOLO AVISO: exige decisión humana ───────────────────────────
            if r.Priority and r.Priority not in CANON_PRIO:
                avisos.append((r.ID_Tasks, "prioridad fuera de vocabulario",
                               f"{r.Priority!r} — decide si mapear o vaciar"))
            if r.Delivery_date and r.Designation_date and r.Delivery_date < r.Designation_date:
                dias = (r.Delivery_date - r.Designation_date).days
                avisos.append((r.ID_Tasks, "entrega antes que designación",
                               f"{r.Designation_date} → {r.Delivery_date} ({dias} días)"))
            if not r.Name:
                avisos.append((r.ID_Tasks, "sin nombre", "fila fantasma"))
            if not r.Task_status:
                avisos.append((r.ID_Tasks, "sin estado", "no cae en ninguna columna del kanban"))
            if not r.ID_Jobs and not r.ID_Subcontractor:
                avisos.append((r.ID_Tasks, "sin job ni subcontratista", "huérfana de verdad"))

        if APLICAR and arreglos:
            s.commit()

    modo = "APLICADO" if APLICAR else "DRY-RUN (no se escribió nada)"
    print(f"\n═══ Saneamiento de tasks · {modo} ═══")
    print(f"Filas revisadas: {len(filas)}\n")

    print(f"── Arreglos inequívocos: {len(arreglos)}")
    for tid, campo, antes, despues in arreglos:
        print(f"   {tid}  {campo}: {antes!r} → {despues!r}")
    if not arreglos:
        print("   (ninguno)")

    print(f"\n── Avisos que exigen decisión humana: {len(avisos)}")
    for tid, tipo, detalle in avisos:
        print(f"   {tid}  {tipo}: {detalle}")
    if not avisos:
        print("   (ninguno)")

    if not APLICAR and arreglos:
        print(f"\nPara aplicar los {len(arreglos)} arreglos: añade --aplicar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
