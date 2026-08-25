"""El webhook borraba EstimateCost APROBADOS por un desajuste que la app fabrica.

`sync_bdf_from_podio` compara cuantos importes BDF trae Podio contra los
EstimateCost aprobados del job y, si hay mas locales, los BORRA
(`session.delete`) — sin auditoria, sin dead-letter y SIN COLUMNA DE
SOFT-DELETE: la fila no es recuperable.

Y el desajuste esta GARANTIZADO POR CONSTRUCCION: `_build_bdf_array` trunca a
BDF_SLOTS = 3 (job_calculator.py:95) y el mapa declara exactamente 3
external_ids, asi que un 4.o BDF aprobado NUNCA puede escribirse en Podio. En el
siguiente `item.update`, Podio trae 3, aqui hay 4, y el 4.o desaparece.

Ni el POST ni el PATCH de /estimate limitaban el numero.

En produccion (25-ago-2026) solo 4 jobs tienen BDF aprobados y el maximo es
exactamente 3. Eso NO prueba que nunca haya pasado: sin soft-delete, un 4.o
borrado por este camino no deja rastro. Lo que si esta probado es que el
desajuste es fabricable.
"""
import ast
import inspect
import textwrap

import pytest

import src.podio.webhook.jobs_hook_sync as jhs
from src.utils.job_calculator import BDF_SLOTS


class _Coste:
    def __init__(self, ident, precio=100.0):
        self.ID_EstimateCost = ident
        self.Client_price = precio
        self.Builder_cost = precio


class _Job:
    ID_Jobs = "QID61359"
    podio_item_id = "3321543437"

    def __init__(self, bdfs_en_podio):
        self.Bldg_dept_fees = bdfs_en_podio


class _Sesion:
    def __init__(self, aprobados):
        self.aprobados = aprobados
        self.borrados, self.anadidos = [], []

    def exec(self, _stmt):
        return self

    def all(self):
        return self.aprobados

    def add(self, obj):
        self.anadidos.append(obj)

    def delete(self, obj):
        self.borrados.append(obj)


@pytest.fixture(autouse=True)
def _sin_dead_letter(monkeypatch):
    registradas = []
    monkeypatch.setattr(jhs, "record_failed_sync_propia",
                        lambda **kw: registradas.append(kw), raising=False)
    return registradas


# --------------------------------------------------------------------------
# El defecto: 4 aprobados, 3 huecos, y se borraba el cuarto
# --------------------------------------------------------------------------
def test_un_cuarto_bdf_aprobado_no_se_borra(_sin_dead_letter):
    """Podio solo puede traer 3. Borrar el 4.o es destruir un coste aprobado
    por un limite NUESTRO, no por una baja del cliente."""
    aprobados = [_Coste(f"EST{i}") for i in range(1, 5)]
    sesion = _Sesion(aprobados)

    jhs.sync_bdf_from_podio(sesion, _Job([100.0, 100.0, 100.0]))

    assert sesion.borrados == [], (
        f"borro {len(sesion.borrados)} coste(s) aprobado(s) irrecuperables por "
        f"un desajuste que la propia app fabrica")


def test_el_desajuste_queda_registrado(_sin_dead_letter):
    """No basta con no borrar: alguien tiene que enterarse."""
    jhs.sync_bdf_from_podio(
        _Sesion([_Coste(f"EST{i}") for i in range(1, 5)]),
        _Job([100.0, 100.0, 100.0]))

    assert _sin_dead_letter, "no dejo rastro del desajuste"
    payload = _sin_dead_letter[0]["payload"]
    assert payload["aprobados"] == 4
    assert payload["slots_en_podio"] == BDF_SLOTS


def test_la_poda_normal_se_mantiene(_sin_dead_letter):
    """Si en Podio borraron uno DE VERDAD (y caben), eso si es una baja."""
    aprobados = [_Coste("EST1"), _Coste("EST2"), _Coste("EST3")]
    sesion = _Sesion(aprobados)

    jhs.sync_bdf_from_podio(sesion, _Job([100.0]))

    assert sesion.borrados == aprobados[1:], (
        "dejo de podar una baja legitima hecha en Podio")


def test_sin_desajuste_no_borra_nada(_sin_dead_letter):
    sesion = _Sesion([_Coste("EST1"), _Coste("EST2")])
    jhs.sync_bdf_from_podio(sesion, _Job([100.0, 100.0]))
    assert sesion.borrados == []


# --------------------------------------------------------------------------
# La otra mitad: que no se pueda fabricar el desajuste
# --------------------------------------------------------------------------
def test_hay_guarda_que_impide_aprobar_un_cuarto_bdf():
    import src.routes.EstimateCost as ec

    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(ec._rechazar_si_no_cabe_otro_bdf))))
    assert "BDF_SLOTS" in codigo, "el limite esta a mano en vez de BDF_SLOTS"
    assert "bdf_slots_agotados" in codigo


@pytest.mark.parametrize("ruta", ["create_estimate", "update_estimate"])
def test_el_post_y_el_patch_llaman_a_la_guarda(ruta):
    """El PATCH importa tanto como el POST: poner Status=Approved es
    exactamente el camino por el que se cuela el 4.o."""
    import src.routes.EstimateCost as ec

    fn = getattr(ec, ruta)
    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(getattr(fn, "__wrapped__", fn)))))
    assert "_rechazar_si_no_cabe_otro_bdf" in codigo, (
        f"{ruta} no limita el numero de BDF aprobados")


def test_el_borrado_del_webhook_usa_bdf_slots():
    """Si el limite se escribe a mano, se desincroniza del truncado."""
    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(jhs.sync_bdf_from_podio))))
    assert "BDF_SLOTS" in codigo
