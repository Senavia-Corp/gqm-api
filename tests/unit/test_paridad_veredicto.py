"""El veredicto de paridad no puede salir verde con errores que se compensan.

Regresión real, medida contra PRODUCCIÓN el 11-ago-2026:

    PTL2026   ok = True   delta = 0
      Podio 35 · BD 35
      FALTAN: PTL6024 (item 3307817034) no tenía fila en la BD

Cuadraba porque `delta` restaba `bd.por_anio`, que incluye los jobs locales sin
`podio_item_id`: el local PTL-I60001 ocupaba el hueco del item ausente. El
semáforo daba verde con un trabajo real perdido — y es exactamente la
comprobación que el cliente iba a hacer a ojo (contador de Podio contra el
total del panel) antes de firmar la entrega.

Dos reglas, una por test:
  1. se compara contra las filas que PUEDEN emparejar (`con_item_id`)
  2. si se enumeró, mandan los conjuntos; el conteo ya no decide
"""
import pytest

from src.routes.podio_routes import Paridad


class _ServicioFalso:
    """Una app de Podio con un conjunto conocido de items."""

    def __init__(self, items):
        self.app_id = "30577946"
        self._items = items

    def get_items_page(self, limit, offset=0):
        lote = self._items[offset:offset + limit]
        return {"items": lote, "filtered": len(self._items),
                "total": len(self._items)}


class _SesionFalsa:
    """Devuelve las filas (ID_Jobs, podio_item_id) que se le den."""

    def __init__(self, filas):
        self._filas = filas

    def exec(self, _stmt):
        return self

    def all(self):
        return self._filas

    def one(self):  # no se usa: _conteo_bd va monkeypatcheado
        raise AssertionError("_conteo_bd deberia estar parcheado")


def _montar(monkeypatch, items_podio, filas_bd):
    """Un año con `items_podio` en Podio y `filas_bd` en la BD."""
    monkeypatch.setattr(Paridad.podio_jobs_router, "get_readonly_service",
                        lambda t, y: _ServicioFalso(items_podio))
    monkeypatch.setattr(Paridad, "_anios_de_la_misma_app", lambda t, a: [2026])

    def _conteo(session, job_type, anios, solo_con_item=False):
        return len([f for f in filas_bd if f[1]]) if solo_con_item else len(filas_bd)

    monkeypatch.setattr(Paridad, "_conteo_bd", _conteo)
    return _SesionFalsa(filas_bd)


def test_un_job_local_no_puede_tapar_un_item_ausente(monkeypatch):
    """El caso de PTL2026 tal cual se midió en producción."""
    # Podio tiene 2 items; la BD tiene 2 filas pero una es local (sin item_id),
    # asi que en realidad le FALTA el item 200. Los conteos brutos cuadran.
    items = [{"item_id": 100, "app_item_id_formatted": "PTL6001"},
             {"item_id": 200, "app_item_id_formatted": "PTL6024"}]
    filas = [("PTL6001", "100"), ("PTL-I60001", None)]

    ses = _montar(monkeypatch, items, filas)
    r = Paridad._paridad_de_app(ses, "PTL", 2026, enumerar=True)

    assert r["bd"]["por_anio"] == 2
    assert r["bd"]["con_item_id"] == 1, "el local no puede contar como emparejable"
    assert r["bd"]["locales_sin_item"] == 1
    assert r["delta"] == 1, "2 en Podio contra 1 emparejable"
    assert [f["app_item_id_formatted"] for f in r["faltan"]] == ["PTL6024"]
    assert r["ok"] is False, (
        "REGRESIÓN: el veredicto vuelve a ser verde con un item ausente tapado "
        "por un job local — justo el falso positivo medido en PTL2026")


def test_sin_enumerar_avisa_de_que_el_conteo_no_basta(monkeypatch):
    items = [{"item_id": 100, "app_item_id_formatted": "PTL6001"}]
    filas = [("PTL6001", "100")]
    ses = _montar(monkeypatch, items, filas)

    r = Paridad._paridad_de_app(ses, "PTL", 2026, enumerar=False)

    assert r["ok"] is True
    assert "veredicto_parcial" in r, (
        "sin enumerar, coincidir es necesario pero no suficiente: hay que decirlo")


def test_los_conjuntos_mandan_sobre_el_conteo(monkeypatch):
    """Un faltan y un sobran a la vez: delta 0 y aun asi NO es paridad."""
    items = [{"item_id": 100, "app_item_id_formatted": "PTL6001"},
             {"item_id": 200, "app_item_id_formatted": "PTL6002"}]
    # la BD tiene 2 con item_id, pero una apunta a un item que ya no esta
    filas = [("PTL6001", "100"), ("PTL6099", "999")]

    ses = _montar(monkeypatch, items, filas)
    r = Paridad._paridad_de_app(ses, "PTL", 2026, enumerar=True)

    assert r["delta"] == 0, "los conteos se compensan"
    assert len(r["faltan"]) == 1 and len(r["sobran"]) == 1
    assert r["ok"] is False, "delta 0 con un hueco y un sobrante no es paridad"


def test_quedarse_sin_reloj_no_se_confunde_con_paridad(monkeypatch):
    """Presupuesto agotado = media medida, y hay que decirlo.

    Sin esto, QID2025 (1880 items) es inverificable: el filtro de Podio
    devuelve el item completo y una pagina de 500 tarda ~100 s, asi que la
    funcion muere en el techo de 300 s. Medido en QID2026: 296,6 s.
    """
    items = [{"item_id": i, "app_item_id_formatted": f"PTL{i}"} for i in range(3)]
    filas = [(f"PTL{i}", str(i)) for i in range(3)]
    ses = _montar(monkeypatch, items, filas)

    # presupuesto 0 => se corta en cuanto pasa la primera pagina
    monkeypatch.setattr(Paridad, "TOPE_PAGINA", 1)
    r = Paridad._paridad_de_app(ses, "PTL", 2026, enumerar=True, presupuesto_s=0)

    assert r["completo"] is False
    assert r["siguiente_offset"] is not None
    assert r["ok"] is False, "media enumeracion no puede dar verde"
    assert "faltan" not in r, (
        "con la app a medias, calcular faltan inventa huecos que no existen")


def test_un_tramo_intermedio_no_inventa_huecos(monkeypatch):
    """Con offset>0 esta llamada solo ve su tramo: no le toca comparar."""
    items = [{"item_id": i, "app_item_id_formatted": f"PTL{i}"} for i in range(3)]
    filas = [(f"PTL{i}", str(i)) for i in range(3)]
    ses = _montar(monkeypatch, items, filas)

    r = Paridad._paridad_de_app(ses, "PTL", 2026, enumerar=True, offset=2)

    assert r["ok"] is False and "parcial" in r
    assert "faltan" not in r


def test_desalineado_tambien_tumba_el_veredicto(monkeypatch):
    """ID_Jobs != app_item_id_formatted = la secuencia nativa se rompio."""
    items = [{"item_id": 100, "app_item_id_formatted": "PTL6001"}]
    filas = [("PTL9999", "100")]  # emparejan por item_id pero el ID no cuadra

    ses = _montar(monkeypatch, items, filas)
    r = Paridad._paridad_de_app(ses, "PTL", 2026, enumerar=True)

    assert r["delta"] == 0 and not r["faltan"] and not r["sobran"]
    assert len(r["desalineados"]) == 1
    assert r["ok"] is False, (
        "la prueba que le importa al cliente es que ID_Jobs == la clave de Podio")
