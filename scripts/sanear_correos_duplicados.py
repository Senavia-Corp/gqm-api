"""Saneamiento de correos duplicados — idempotente y con DRY-RUN por defecto.

Prerrequisito de la migracion `e9c1correo`, que crea el indice unico sobre
lower(Email_Address) en member, subcontractor y technician. Si hay duplicados,
esa migracion se para en seco con la lista en vez de dejar un indice invalido.

QUE ARREGLA Y QUE NO
====================
Mismo criterio que `scripts/sanear_tasks.py`: se arregla SOLO lo que tiene una
correspondencia inequivoca; todo lo demas se REPORTA, porque resolverlo exigiria
adivinar cual de dos personas es la buena, y adivinar identidades es peor que
dejar el dato sucio.

  · INEQUIVOCO — de N filas que comparten correo, exactamente UNA tiene
    contrasena utilizable. Las otras no pueden iniciar sesion hoy ni podran
    nunca (el login resuelve siempre a una sola fila). Se les vacia el correo,
    que es lo que bloquea el indice. La fila se conserva: no se borra nada.

  · AMBIGUO — dos o mas filas del mismo correo CON contrasena, o ninguna con
    contrasena. Se reporta con sus ids para que lo decida una persona. Aqui el
    script no toca nada.

Uso:
    .venv/bin/python scripts/sanear_correos_duplicados.py            # informe
    .venv/bin/python scripts/sanear_correos_duplicados.py --aplicar  # escribe
    .venv/bin/python scripts/sanear_correos_duplicados.py --aplicar --permitir-produccion
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decouple import config  # noqa: E402
from sqlmodel import select  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.MemberModel import Member  # noqa: E402
from src.models.SubcontractorModel import Subcontractor  # noqa: E402
from src.models.TechnicianModel import Technician  # noqa: E402
from src.utils.db_guard import classify_database_url  # noqa: E402

APLICAR = "--aplicar" in sys.argv
PROD_OK = "--permitir-produccion" in sys.argv

DB = config("DATABASE_URL", default="")
if classify_database_url(DB) == "rechazado" and not PROD_OK:
    sys.exit("⛔ La BD no es Neon develop ni loopback. "
             "Usa --permitir-produccion si es intencional.")
if PROD_OK and APLICAR:
    print("⚠️  MODO PRODUCCION CON ESCRITURA. Ctrl-C en 5 s para abortar.")
    import time
    time.sleep(5)

MODELOS = [(Member, "ID_Member"), (Subcontractor, "ID_Subcontractor"),
           (Technician, "ID_Technician")]


def main() -> None:
    arreglados = ambiguos = 0
    with get_session() as session:
        for Modelo, id_col in MODELOS:
            filas = session.exec(select(Modelo)).unique().all()
            por_correo = defaultdict(list)
            for f in filas:
                correo = (getattr(f, "Email_Address", None) or "").strip().lower()
                if correo:
                    por_correo[correo].append(f)

            for correo, grupo in sorted(por_correo.items()):
                if len(grupo) < 2:
                    continue
                ids = [getattr(f, id_col) for f in grupo]
                con_clave = [f for f in grupo if getattr(f, "Password", None)]

                if len(con_clave) == 1:
                    conserva = getattr(con_clave[0], id_col)
                    sobran = [f for f in grupo if f is not con_clave[0]]
                    print(f"  ✔ {Modelo.__name__}: «{correo}» en {ids} — "
                          f"solo {conserva} tiene contrasena; "
                          f"se vacia el correo de {[getattr(f, id_col) for f in sobran]}")
                    if APLICAR:
                        for f in sobran:
                            # Cadena VACIA, no None: `Email_Address` es NOT NULL
                            # en `technician` y en `member` (comprobado contra
                            # information_schema), asi que poner None reventaba
                            # con NotNullViolation — el script no podia sanear
                            # justo el caso que la migracion exige sanear.
                            #
                            # El indice excluye '' con su predicado btrim, asi
                            # que la fila deja de bloquear el correo. Y se
                            # IMPRIME el valor que se quita: la fila se conserva,
                            # pero el dato hay que poder recuperarlo.
                            print(f"      · {getattr(f, id_col)} tenia "
                                  f"«{f.Email_Address}» → se vacia")
                            f.Email_Address = ""
                            session.add(f)
                    arreglados += len(sobran)
                else:
                    motivo = ("ninguna tiene contrasena" if not con_clave
                              else f"{len(con_clave)} tienen contrasena")
                    print(f"  ⚠ {Modelo.__name__}: «{correo}» en {ids} — AMBIGUO "
                          f"({motivo}). Lo decide una persona; aqui no se toca.")
                    ambiguos += 1

        if APLICAR:
            session.commit()

    print()
    if not arreglados and not ambiguos:
        print("✅ no hay correos duplicados: la migracion e9c1correo puede correr.")
    else:
        print(f"{'APLICADO' if APLICAR else 'DRY-RUN'}: "
              f"{arreglados} filas saneables, {ambiguos} grupos ambiguos.")
        if ambiguos:
            print("⛔ Con grupos ambiguos sin resolver, la migracion e9c1correo "
                  "seguira abortando. Resuelvelos a mano primero.")
        elif not APLICAR:
            print("   Repite con --aplicar para escribir.")


if __name__ == "__main__":
    main()
