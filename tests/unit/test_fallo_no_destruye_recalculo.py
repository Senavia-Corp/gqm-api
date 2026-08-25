"""Registrar un fallo de sincronizacion destruia el recalculo que ya estaba bien.

`record_failed_sync` ejecuta `session.rollback()` como PRIMERA instruccion
(failed_sync.py:15) sobre la sesion VIVA del route. Cadena concreta en
POST/PATCH /estimate:

    save_with_retry(...)        -> COMMIT del EstimateCost
    recalculate_and_apply(...)  -> escribe los agregados EN MEMORIA (sin commit)
    sync_job_to_podio(...)      -> intenta el PUT a Podio

Si Podio fallaba, el rollback se llevaba por delante EL RECALCULO: el coste
existia, el job conservaba los agregados VIEJOS, y el panel ensenaba un total
que no cuadra con sus hijos.

Y el camino de recuperacion era peor que inutil: la fila quedaba como
`auto_sync_to_podio` y el resync llamaba a `sync_job_to_podio` SIN volver a
recalcular — re-empujaba el valor viejo y lo cerraba como exito.
"""
import ast
import inspect
import textwrap
from contextlib import contextmanager

import pytest

import src.utils.podio_job_sync as pjs


class _Job:
    ID_Jobs = "QID61359"
    Job_type = "QID"
    podio_item_id = "3321543437"


class _SesionViva:
    """La sesion del route. Cuenta rollbacks: cada uno se lleva el recalculo."""

    def __init__(self):
        self.rollbacks = 0
        self.commits = 0

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def add(self, _o):
        pass

    def get(self, _m, _i):
        return _Job()


class _SesionPropia(_SesionViva):
    pass


# --------------------------------------------------------------------------
# El arreglo de raiz
# --------------------------------------------------------------------------
def test_registrar_el_fallo_no_toca_la_sesion_del_route(monkeypatch):
    """EL DEFECTO: el rollback caia sobre la sesion viva."""
    viva, propia = _SesionViva(), _SesionPropia()

    @contextmanager
    def _get_session():
        yield propia

    monkeypatch.setattr(
        "src.database.db_sqlmodel.get_session", _get_session)

    pjs._record_failed_sync(viva, _Job(), "Podio 503")

    assert viva.rollbacks == 0, (
        "hizo rollback sobre la sesion del route: se lleva por delante el "
        "recalculo de agregados que aun no estaba commiteado")
    assert propia.rollbacks == 1, "no registro el fallo en su propia sesion"


def test_si_falla_el_registro_no_tumba_al_llamador(monkeypatch):
    """Registrar un fallo no puede convertirse en un fallo peor."""
    @contextmanager
    def _revienta():
        raise RuntimeError("BD caida")
        yield

    monkeypatch.setattr(
        "src.database.db_sqlmodel.get_session", _revienta)

    pjs._record_failed_sync(_SesionViva(), _Job(), "Podio 503")  # no lanza


def test_usa_get_session_y_no_la_que_le_pasan():
    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(pjs._record_failed_sync))))
    assert "get_session()" in codigo, (
        "sigue escribiendo con la sesion del llamador")


# --------------------------------------------------------------------------
# El recalculo se commitea ANTES de salir a Podio
# --------------------------------------------------------------------------
@pytest.mark.parametrize("modulo", [
    "src.routes.EstimateCost", "src.routes.Purchase",
    "src.routes.PurchaseOrder", "src.routes.PurchaseOrderItem",
])
def test_el_recalculo_se_commitea_antes_del_sync(modulo):
    """Defensa en profundidad: si algo escapa de sync_job_to_podio, el
    recalculo ya esta a salvo en disco."""
    import importlib
    import pathlib

    mod = importlib.import_module(modulo)
    fuente = pathlib.Path(mod.__file__).read_text(encoding="utf-8")

    lineas = [l.strip() for l in fuente.split("\n")]
    for i, linea in enumerate(lineas):
        if linea.startswith("sync_job_to_podio("):
            previas = [l for l in lineas[max(0, i - 8):i]
                       if l and not l.startswith("#") and not l.startswith("from ")]
            assert previas and previas[-1] == "session.commit()", (
                f"{modulo}:{i + 1} sale a Podio sin commitear el recalculo; "
                f"lo anterior era: {previas[-3:]}")


def test_el_resync_recalcula_antes_de_re_empujar():
    """Sin esto, reintentar re-empuja el valor VIEJO y lo cierra como exito."""
    import src.routes.Webhook_bp as wb

    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(wb.resync_failed_sync.__wrapped__))))

    i_auto = codigo.find("auto_sync_to_podio")
    assert i_auto > 0
    tramo = codigo[i_auto:i_auto + 900]
    i_recalc = tramo.find("recalculate_and_apply")
    i_sync = tramo.find("sync_job_to_podio(")

    assert i_recalc != -1, (
        "el resync re-empuja sin recalcular: manda el valor viejo y cierra la "
        "falla como resuelta, fijando la divergencia")
    assert i_recalc < i_sync, "recalcula DESPUES de empujar: llega tarde"
