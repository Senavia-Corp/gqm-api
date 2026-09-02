"""`POST /order` colaba una segunda Order en un slot ya ocupado.

El guard que ya existia —`is_primary_taken`, order_changeorder_mappers.py:160—
mira la CASILLA DE PODIO, no la BD. Ese desfase es el mecanismo real del unico
duplicado vivo de `"order"`, y no la carrera de `upsert_order` que documentaban
la migracion y el runbook. Reconstruido desde `tlactivity` de PAR6095:

    18-ago-2026 18:56:18  MEM60012 borra PO-PAR6095-0363
    18-ago-2026 19:03:10  MEM60012 la vuelve a crear  -> ORD69726

Siete minutos, una persona, la misma PO: eso no es una carrera. Lo que paso es
que el DELETE pre-#129 emitio `[]` y dejo la casilla de Podio VACIA mientras
ORD68994 seguia en la BD ocupando `tech-1-ptl-original-pricing`; el CREATE de
siete minutos despues pregunto a Podio, vio la casilla libre, y colo la segunda.

Con `ux_order_job_slot` puesto el INSERT ya no duplica — pero sin este guard
revienta con un 500 sin explicacion en vez del 409 que el guard de Podio ya
pretendia dar.
"""
import ast
import inspect
import textwrap

import pytest
from sqlalchemy.exc import IntegrityError

import src.routes.Order as O


class _Fila:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _NoAutoflush:
    """Sustituto de `Session.no_autoflush`. Anota que se entro en el."""

    def __init__(self, sesion):
        self.sesion = sesion

    def __enter__(self):
        self.sesion.dentro_de_no_autoflush = True
        return self

    def __exit__(self, *a):
        return False


class _Sesion:
    """Devuelve `ocupante` a cualquier SELECT, y cuenta si se le pregunto."""

    def __init__(self, ocupante=None):
        self.ocupante = ocupante
        self.consultas = 0
        self.condiciones = None
        self.dentro_de_no_autoflush = False

    @property
    def no_autoflush(self):
        return _NoAutoflush(self)

    def exec(self, stmt):
        self.consultas += 1
        self.condiciones = stmt
        return self

    def first(self):
        return self.ocupante


def _choque(indice):
    return IntegrityError("INSERT", {}, Exception(
        f'duplicate key value violates unique constraint "{indice}"'))


# --------------------------------------------------------------------------
# _slot_ocupado: la BD manda sobre el slot
# --------------------------------------------------------------------------
def test_detecta_al_ocupante_del_slot():
    ocupante = _Fila(ID_Order="ORD68994")
    sesion = _Sesion(ocupante)

    assert O._slot_ocupado(
        sesion, "3304340068", "tech-1-ptl-original-pricing") is ocupante


def test_slot_libre_devuelve_none():
    assert O._slot_ocupado(
        _Sesion(None), "3304340068", "tech-1-ptl-original-pricing") is None


def test_consulta_sin_autoflush():
    """Con sync_podio=true la orden en curso ya esta en la sesion cuando el
    mapper le pone el `tech_field`. Un SELECT con autoflush la volcaria, y el
    INSERT chocaria con `ux_order_job_slot` AQUI —500 crudo— en vez de dejar
    contestar el 409 que se esta calculando."""
    sesion = _Sesion(None)

    O._slot_ocupado(sesion, "3304340068", "tech-1-ptl-original-pricing")

    assert sesion.dentro_de_no_autoflush, "consulto con autoflush activo"


def test_excluye_la_orden_en_curso():
    """Sin `excluir`, `.first()` puede devolver la propia orden recien volcada y
    dar por libre un slot que otra fila ya ocupa."""
    sesion = _Sesion(None)

    O._slot_ocupado(sesion, "3304340068", "tech-1-ptl-original-pricing",
                    excluir="ORD69726")

    assert "ORD69726" in str(sesion.condiciones.compile(
        compile_kwargs={"literal_binds": True})), (
        "la consulta no excluye la orden en curso")


@pytest.mark.parametrize("job_podio_id, tech_field", [
    (None, "tech-1-ptl-original-pricing"),
    ("3304340068", None),
    ("", "tech-1-ptl-original-pricing"),
    ("3304340068", ""),
    (None, None),
])
def test_sin_slot_no_consulta_la_bd(job_podio_id, tech_field):
    """503 de las 9.801 orders no tienen slot. Un SELECT con un lado a NULL no
    empareja nunca en SQL, asi que preguntar seria trabajo tirado — y el indice
    es PARCIAL justo para no colisionarlas entre ellas."""
    sesion = _Sesion(_Fila(ID_Order="ORD68994"))

    assert O._slot_ocupado(sesion, job_podio_id, tech_field) is None
    assert sesion.consultas == 0, "consulto la BD con el slot incompleto"


# --------------------------------------------------------------------------
# _es_choque_de_slot: no disfrazar otros fallos de conflicto de slot
# --------------------------------------------------------------------------
def test_reconoce_el_choque_del_indice_de_slot():
    assert O._es_choque_de_slot(_choque("ux_order_job_slot"))


@pytest.mark.parametrize("indice", [
    "ux_jobs_podio_item_id",
    "ux_attachments_podio_file_id",
    "order_pkey",
])
def test_otro_integrityerror_no_se_toma_por_conflicto_de_slot(indice):
    """Tragarse cualquier IntegrityError mandaria al usuario a 'editar la
    existente' sobre una orden que no existe."""
    assert not O._es_choque_de_slot(_choque(indice))


# --------------------------------------------------------------------------
# El guard esta enganchado donde toca dentro de create_order
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def codigo_create_order():
    return ast.unparse(ast.parse(
        textwrap.dedent(inspect.getsource(O.create_order))))


def test_comprueba_el_slot_antes_de_quemar_un_id(codigo_create_order):
    """`generate_custom_id` commitea aparte desde c5a8e3f24b17: un rollback ya
    no devuelve el numero. Rechazar despues de pedirlo quema un ORD por nada."""
    i_guard = codigo_create_order.find("_slot_ocupado")
    i_id = codigo_create_order.find("generate_custom_id")

    assert i_guard != -1, "create_order no comprueba el slot contra la BD"
    assert i_guard < i_id, "comprueba el slot DESPUES de pedir el ID"


def test_vuelve_a_comprobar_tras_asignar_el_slot_desde_podio(codigo_create_order):
    """Con sync_podio=true el `tech_field` no viene en el body: lo asigna
    `map_order_create_to_podio` mirando Podio. Ese es el caso que fallo el
    18-ago, asi que la BD tiene que opinar DESPUES de esa asignacion."""
    i_mapper = codigo_create_order.find("map_order_create_to_podio")
    assert i_mapper != -1

    assert codigo_create_order.find("_slot_ocupado", i_mapper) != -1, (
        "no revalida el slot despues de que el mapper lo asigne desde Podio")


def test_los_dos_caminos_de_guardado_traducen_el_choque(codigo_create_order):
    """El pre-chequeo no cubre la carrera de verdad: entre el SELECT y el commit
    cabe otra creacion. El indice la para; hay que traducirla, no devolver 500.

    Son dos caminos distintos: `session.commit()` con sync_podio=true y
    `save_with_retry` con sync_podio=false — y `save_with_retry` propaga el
    IntegrityError sin reintentar (add_session.py)."""
    assert codigo_create_order.count("_es_choque_de_slot") == 2, (
        "algun camino de guardado deja subir el IntegrityError como 500")
    assert codigo_create_order.count("order_slot_taken") == 4, (
        "los dos pre-chequeos y los dos catch tienen que dar el mismo codigo")


def test_el_409_lleva_el_mensaje_que_el_guard_de_podio_ya_daba():
    """Mismo texto que `is_primary_taken`: el usuario ve una sola explicacion,
    venga el rechazo de Podio o de la BD."""
    assert "Edite la existente" in O.SLOT_OCUPADO
