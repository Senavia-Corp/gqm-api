"""La carrera de generate_custom_id, ejercitada de verdad contra PostgreSQL.

El algoritmo anterior hacia `SELECT` de los IDs del prefijo+año y `max+1` EN
PYTHON, sin lock: check-then-act. Medido en DEV el 21-ago-2026 con N sesiones
lanzadas a la vez con `threading.Barrier`:

    2 sesiones -> 0 colisiones     5 sesiones -> 3 colisiones (60% perdido)
    3 sesiones -> 1 colision       8 sesiones -> 6 colisiones (75% perdido)

Evidencia en produccion (`podio_failed_syncs` id 7..11): el item 3345393757
(PAR6171) entro CINCO veces en 1,6 s y cuatro reventaron con
`duplicate key ... "attachments_pkey"`.

Estos tests NO afirman sobre el texto del fuente —como hacia
`test_adjuntos_carrera_concurrente.py`, que pasa aunque la logica este
invertida— sino que lanzan hilos de verdad contra Neon develop, igual que
`test_webhook_idempotencia.py` ya hacia con `threading.Barrier(2)`.

Con el codigo anterior, `test_ocho_a_la_vez_no_colisionan` FALLA.
"""
import threading
import uuid
from typing import Optional

import pytest
from sqlalchemy import text
from sqlmodel import Field, Session, SQLModel

from src.database.db_sqlmodel import engine
from src.utils.id_generator import generate_custom_id


class _FilaPg(SQLModel, table=True):
    __tablename__ = "fila_prueba_idgen_pg"
    ID_Cosa: Optional[str] = Field(default=None, primary_key=True)


@pytest.fixture()
def tabla():
    SQLModel.metadata.create_all(engine, tables=[_FilaPg.__table__])
    prefijo = f"ZZ{uuid.uuid4().hex[:3].upper()}"
    yield prefijo
    with engine.connect() as c:
        c.execute(text('DELETE FROM fila_prueba_idgen_pg WHERE "ID_Cosa" LIKE :p'),
                  {"p": f"{prefijo}%"})
        c.execute(text("DELETE FROM id_counters WHERE prefix = :p"), {"p": prefijo})
        c.commit()


def test_ocho_a_la_vez_no_colisionan(tabla):
    """Los mismos 8 con los que se midio el 75% de perdida."""
    N = 8
    barrera = threading.Barrier(N)
    obtenidos, errores = [], []
    cerrojo = threading.Lock()

    def trabajador():
        try:
            with Session(engine) as s:
                barrera.wait(timeout=30)
                nuevo = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)
                s.add(_FilaPg(ID_Cosa=nuevo))
                s.commit()
            with cerrojo:
                obtenidos.append(nuevo)
        except Exception as e:  # noqa: BLE001
            with cerrojo:
                errores.append(f"{type(e).__name__}: {e}")

    hilos = [threading.Thread(target=trabajador) for _ in range(N)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    assert not errores, f"ningun hilo deberia fallar: {errores}"
    assert len(set(obtenidos)) == N, (
        f"{N} hilos produjeron solo {len(set(obtenidos))} IDs distintos: "
        f"{sorted(obtenidos)}. Con el max+1 en Python aqui se perdian 6 de 8."
    )

    with engine.connect() as c:
        filas = c.execute(
            text('SELECT count(*) FROM fila_prueba_idgen_pg WHERE "ID_Cosa" LIKE :p'),
            {"p": f"{tabla}%"}).scalar()
    assert filas == N, f"esperaba {N} filas insertadas, hay {filas}"


def test_siembra_desde_el_maximo_existente(tabla):
    """El contador arranca donde estaba la tabla, no en 1.

    Si sembrara desde cero, el primer ID chocaria con los ya existentes — que
    es como se pierden filas en silencio.
    """
    from datetime import datetime
    d = str(datetime.now().year)[-1]

    with Session(engine) as s:
        s.add(_FilaPg(ID_Cosa=f"{tabla}{d}0007"))
        s.commit()
        nuevo = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)

    assert nuevo == f"{tabla}{d}0008", f"esperaba …0008, salio {nuevo}"


def test_los_ids_legacy_sin_sufijo_no_reinician_el_contador(tabla):
    """Un ID como "BLGDEP6" (sin numero) debe IGNORARSE, no valer 0.

    Si contara como 0, el siguiente ID seria …0001 y colisionaria con los ya
    usados. Es el mismo invariante que protege el algoritmo anterior.
    """
    from datetime import datetime
    d = str(datetime.now().year)[-1]

    with Session(engine) as s:
        s.add(_FilaPg(ID_Cosa=f"{tabla}{d}"))        # sin sufijo numerico
        s.add(_FilaPg(ID_Cosa=f"{tabla}{d}0042"))
        s.commit()
        nuevo = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)

    assert nuevo == f"{tabla}{d}0043", f"esperaba …0043, salio {nuevo}"


def test_no_ensucia_la_sesion_del_llamador(tabla):
    """El invariante que mato produccion en agosto.

    La cadena de los 12 ficheros perdidos fue: `session.add()` deja un INSERT
    pendiente -> log_activity llama a generate_custom_id -> su SELECT dispara
    AUTOFLUSH -> el INSERT pendiente estalla con UniqueViolation -> se lo traga
    `audit.py:114` -> la sesion queda envenenada -> el commit final revienta con
    PendingRollbackError.

    Con el contador en conexion aparte, generate_custom_id ya no emite SQL sobre
    la sesion del llamador, asi que no puede disparar ese autoflush.
    """
    from datetime import datetime
    d = str(datetime.now().year)[-1]

    with Session(engine) as s:
        s.add(_FilaPg(ID_Cosa=f"{tabla}{d}0001"))
        s.commit()

        # objeto pendiente que reventaria si algo forzara un flush
        s.add(_FilaPg(ID_Cosa=f"{tabla}{d}0001"))
        assert len(s.new) == 1

        generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)

        assert len(s.new) == 1, (
            "generate_custom_id forzo un flush de la sesion del llamador; "
            "esa es exactamente la cadena que perdio 12 ficheros en agosto")
        s.rollback()


# ─────────────────────────────────────────────────────────────────────────
# El CAMINO DE RESPALDO. Lo saco la revision adversarial: los tests de arriba
# solo ejercitaban el camino del contador, que es justo el que nunca falla ni
# hace flush. La red de seguridad estaba sin cubrir — y contenia dos defectos.
# ─────────────────────────────────────────────────────────────────────────

def _forzar_respaldo(monkeypatch):
    """Hace que el contador reviente para caer al algoritmo anterior."""
    from src.utils import id_generator as ig

    def revienta(*a, **k):
        raise RuntimeError("contador caido (simulado)")

    monkeypatch.setattr(ig, "_siguiente_contador", revienta)


def test_el_respaldo_no_ensucia_la_sesion_del_llamador(monkeypatch, tabla):
    """DEFECTO 1 que encontro la revision: el respaldo hacia autoflush.

    `_max_en_python` usaba `session.exec(select(...))`, y `Session.exec`
    AUTOFLUSHEA. Es decir: la red de seguridad contenia exactamente el bug del
    que protege — la cadena que perdio los 12 ficheros de agosto. Y como el
    respaldo salta bajo carga, saltaria en el peor momento.
    """
    from datetime import datetime
    d = str(datetime.now().year)[-1]
    _forzar_respaldo(monkeypatch)

    with Session(engine) as s:
        s.add(_FilaPg(ID_Cosa=f"{tabla}{d}0001"))
        s.commit()

        s.add(_FilaPg(ID_Cosa=f"{tabla}{d}0001"))   # duplicado pendiente
        assert len(s.new) == 1

        generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)

        assert len(s.new) == 1, (
            "el camino de RESPALDO forzo un flush de la sesion ajena; es la "
            "cadena exacta que perdio 12 ficheros en agosto")
        s.rollback()


def test_el_respaldo_deja_el_contador_al_dia(monkeypatch, tabla):
    """DEFECTO 2 que encontro la revision: el respaldo no avanzaba el contador.

    Devolvia `max+1` sin tocar `id_counters`. Si el contador estaba sembrado y
    sincronizado, la SIGUIENTE llamada buena hacia `last_value + 1` y devolvia
    EL MISMO numero -> duplicate key. En log_activity esa IntegrityError la
    absorbe audit.py:114 y la fila de auditoria se pierde en silencio.

    Este test reproduce la secuencia completa: respaldo, luego camino normal.
    """
    from datetime import datetime
    d = str(datetime.now().year)[-1]

    # 1 · una llamada BUENA siembra y sincroniza el contador
    with Session(engine) as s:
        primero = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)
        s.add(_FilaPg(ID_Cosa=primero))
        s.commit()

    # 2 · una llamada por el RESPALDO
    _forzar_respaldo(monkeypatch)
    with Session(engine) as s:
        segundo = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)
        s.add(_FilaPg(ID_Cosa=segundo))
        s.commit()

    # 3 · vuelve el camino normal: NO puede repetir el numero del respaldo
    monkeypatch.undo()
    with Session(engine) as s:
        tercero = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)
        s.add(_FilaPg(ID_Cosa=tercero))
        s.commit()

    assert len({primero, segundo, tercero}) == 3, (
        f"IDs repetidos: {primero=} {segundo=} {tercero=}. Sin reconciliar el "
        f"contador, el tercero repite el segundo y estalla la clave duplicada.")
    assert tercero != segundo


def test_el_respaldo_no_retiene_el_lock_de_id_counters(monkeypatch, tabla):
    """El respaldo no puede bloquear la fila del contador durante la transaccion.

    DEFECTO QUE CUBRE (verificacion adversarial del 21-ago-2026): la primera
    version de `_empujar_contador` escribia con `session.connection()`, o sea la
    transaccion del LLAMADOR. Eso toma el row lock de (prefix, year_digit) y lo
    retiene hasta que esa transaccion commitee — que en el webhook de adjuntos
    incluye dos requests.get a Podio y una subida a Cloudinary.

    Es exactamente el problema por el que el diseno descarto
    `pg_advisory_xact_lock`, reintroducido por la puerta de atras. Y el caso
    peor no es entre peticiones: la siguiente llamada del MISMO request usa la
    conexion autonoma y espera un lock que retiene su propia transaccion. Sin
    ciclo de esperas, el detector de deadlocks de PostgreSQL nunca dispara, y en
    produccion lock_timeout=0.

    Este test comprueba que, tras usar el respaldo, la transaccion del llamador
    NO tiene ningun lock sobre id_counters.
    """
    _forzar_respaldo(monkeypatch)

    with Session(engine) as s:
        generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)

        # la transaccion del llamador sigue ABIERTA aqui
        locks = s.connection().execute(text("""
            SELECT count(*)
              FROM pg_locks l
              JOIN pg_class c ON c.oid = l.relation
             WHERE c.relname = 'id_counters'
               AND l.pid = pg_backend_pid()
               AND l.locktype = 'relation'
        """)).scalar()

        assert locks == 0, (
            f"la transaccion del llamador retiene {locks} lock(s) sobre "
            f"id_counters con la transaccion aun abierta. Esa retencion dura "
            f"hasta el commit — que en el webhook de adjuntos incluye descargas "
            f"de Podio y subidas a Cloudinary.")
        s.rollback()


def test_dos_ids_seguidos_por_el_respaldo_no_se_bloquean(monkeypatch, tabla):
    """El caso que colgaba: dos IDs del mismo prefijo en una transaccion.

    Con el lock retenido por la transaccion del llamador, la segunda llamada
    (por la conexion autonoma) esperaba un lock de su propio request. Sin ciclo
    de esperas, PostgreSQL no lo detecta como deadlock: se cuelga hasta que
    Vercel mata la funcion.
    """
    _forzar_respaldo(monkeypatch)

    with Session(engine) as s:
        primero = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)
        s.add(_FilaPg(ID_Cosa=primero))
        # sin commit: la transaccion sigue abierta, como en el bucle real
        segundo = generate_custom_id(s, _FilaPg, "ID_Cosa", tabla)
        assert segundo != primero
        s.rollback()
