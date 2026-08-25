"""Dos Orders podian ocupar el mismo slot (job_podio_id, tech_field).

`upsert_order` y `upsert_change_order` son check-then-insert sin lock, sin
savepoint y sin `ON CONFLICT`, y hasta ahora nada lo paraba: la tabla no tenia
ninguna restriccion. Entre el SELECT y el INSERT cabe otra entrega del mismo
evento —Podio reintenta y una app puede tener varios hooks— y las dos ven "no
existe".

La asimetria prueba que fue un descuido: `jobs` se blindo con
`ux_jobs_podio_item_id` y `attachments` con `ux_attachments_podio_file_id`.

El dano esta vivo y es exactamente uno (medido el 25-ago-2026): job_podio_id
3304340068 (PAR6095) con ORD68994 (110) y ORD69726 (330) en
`tech-1-ptl-original-pricing`. `recalculate_job_fields` acumula TODAS las orders
del job, asi que suma 660 donde deberia sumar 550.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest
from sqlalchemy.exc import IntegrityError

import src.podio.sync.sync_orders as so

MIGRACION = (pathlib.Path(__file__).parents[2] / "migrations" / "versions" /
             "e7a3c9d21f80_unico_order_change_order_slot.py")


class _Choque(IntegrityError):
    def __init__(self, indice):
        super().__init__("INSERT", {}, Exception(
            f'duplicate key value violates unique constraint "{indice}"'))


class _Sesion:
    """Simula la carrera: el primer INSERT choca, y el SELECT posterior
    devuelve la fila que gano."""

    def __init__(self, ganadora, indice):
        self.ganadora, self.indice = ganadora, indice
        self.intentos, self.anadidos = 0, []
        self._select_inicial = True

    def exec(self, _stmt):
        return self

    def first(self):
        # El primer SELECT (el del check) no ve nada: esa es la carrera.
        if self._select_inicial:
            self._select_inicial = False
            return None
        return self.ganadora

    def add(self, obj):
        self.anadidos.append(obj)

    def flush(self):
        pass

    def begin_nested(self):
        sesion = self

        class _SP:
            def __enter__(self):
                sesion.intentos += 1
                return self

            def __exit__(self, *a):
                if sesion.intentos == 1:
                    raise _Choque(sesion.indice)
                return False
        return _SP()


class _Fila:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture(autouse=True)
def _sin_contador(monkeypatch):
    """`generate_custom_id` pide `session.get_bind()` y toca `id_counters`.

    Aqui lo que se prueba es la carrera del INSERT, no la asignacion de IDs.
    """
    monkeypatch.setattr(so, "generate_custom_id", lambda *a, **k: "ORD-TEST")


# --------------------------------------------------------------------------
# La migracion
# --------------------------------------------------------------------------
def test_los_dos_indices_son_parciales():
    """502 de 9.729 orders no tienen slot, y 2 de 1.283 change orders tampoco.

    Un unico TOTAL las haria colisionar entre ellas. Mismo motivo que en
    ux_attachments_podio_file_id.
    """
    fuente = MIGRACION.read_text(encoding="utf-8")
    for indice in ("ux_order_job_slot", "ux_change_order_job_slot"):
        assert indice in fuente
    assert fuente.count("IS NOT NULL") >= 4, "algun indice no es parcial"


def test_la_migracion_aborta_si_hay_duplicados():
    """Con el duplicado vivo el indice no se puede crear.

    Forzarlo dejaria un indice INVALID, que no impide duplicados: creerse
    protegido sin estarlo es peor que no tenerlo.
    """
    fuente = MIGRACION.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    upgrade = next(n for n in ast.walk(arbol)
                   if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    codigo = ast.unparse(upgrade)

    i_raise = codigo.find("raise RuntimeError")
    i_create = codigo.find("CREATE UNIQUE INDEX")
    assert i_raise != -1, "no comprueba duplicados antes de crear"
    assert i_raise < i_create, "comprueba DESPUES de crear: llega tarde"


def test_usa_concurrently_en_autocommit():
    """La tabla esta en uso; el cliente trabaja mientras esto corre."""
    fuente = MIGRACION.read_text(encoding="utf-8")
    assert "CONCURRENTLY" in fuente
    assert "autocommit_block" in fuente


def test_la_cadena_de_alembic_tiene_una_sola_cabeza():
    """Dos cabezas harian que `alembic upgrade head` se negara a correr."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    raiz = pathlib.Path(__file__).parents[2]
    sc = ScriptDirectory.from_config(Config(str(raiz / "alembic.ini")))
    cabezas = sc.get_heads()
    assert len(cabezas) == 1, f"cadena bifurcada: {cabezas}"

    # Lo que importa es que haya UNA cabeza, no cual: fijar el id aqui obliga a
    # tocar este test en cada migracion futura, y eso lo convierte en ruido.
    # Lo que si se comprueba es que esta revision sigue en la cadena.
    assert any(r.revision == "e7a3c9d21f80" for r in sc.walk_revisions()), (
        "los indices unicos desaparecieron de la cadena de migraciones")


# --------------------------------------------------------------------------
# El savepoint: el perdedor de la carrera actualiza en vez de duplicar
# --------------------------------------------------------------------------
def test_una_order_perdedora_actualiza_en_vez_de_duplicar():
    ganadora = _Fila(ID_Order="ORD69726", Formula=None, Adj_formula=None,
                     ID_Subcontractor=None, Ptl_hd_materials=None, Notes=None)
    sesion = _Sesion(ganadora, "ux_order_job_slot")

    orden, creada = so.upsert_order(
        session=sesion, job=_Fila(ID_Jobs="PAR6095"),
        podio_item_id="3304340068", subcontractor_id="SUBC60341",
        tech_index=1, formula=330, adj_formula=330,
        tech_field="tech-1-ptl-original-pricing",
        hd_materials=None, notes="x")

    assert orden is ganadora, "creo una SEGUNDA fila en el mismo slot"
    assert creada is False
    assert ganadora.Formula == 330, "no propago el valor a la que gano"


def test_un_change_order_perdedor_tambien_actualiza():
    ganadora = _Fila(ID_ChangeOrder="ChO1", ChangeOrderFormula=None, ID_Order=None)
    sesion = _Sesion(ganadora, "ux_change_order_job_slot")

    co, creado = so.upsert_change_order(
        session=sesion, job=_Fila(ID_Jobs="QID1"),
        podio_item_id="330", podio_field="change-order-1",
        change_formula=500)

    assert co is ganadora and creado is False
    assert ganadora.ChangeOrderFormula == 500


def test_un_integrityerror_que_no_es_del_slot_sigue_subiendo():
    """Degradar a UPDATE ante CUALQUIER IntegrityError taparia otros fallos."""
    sesion = _Sesion(_Fila(), "otro_indice_cualquiera")
    with pytest.raises(IntegrityError):
        so.upsert_order(
            session=sesion, job=_Fila(ID_Jobs="PAR6095"),
            podio_item_id="330", subcontractor_id="S1", tech_index=1,
            formula=10, adj_formula=10, tech_field="tech-1-ptl-original-pricing",
            hd_materials=None, notes="x")


@pytest.mark.parametrize("fn", ["upsert_order", "upsert_change_order"])
def test_el_insert_va_dentro_de_un_savepoint(fn):
    """Sin savepoint, el choque se lleva por delante la transaccion entera."""
    codigo = ast.unparse(ast.parse(
        textwrap.dedent(inspect.getsource(getattr(so, fn)))))
    assert "begin_nested" in codigo, f"{fn} sigue insertando sin savepoint"
