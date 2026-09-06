"""Un fallo que no se puede arreglar reintentando debe decirlo, no reintentarse.

Medido en produccion el 6-sep-2026: seis filas abiertas en `podio_failed_syncs`
que eran DOS ficheros. Cada pulsacion de Resync volvia a descargar 18,9 MB de
Podio para chocar contra el mismo tope de Cloudinary, o volvia a preguntar por
un fichero que Podio ya habia borrado (410).

Lo que estos tests vigilan:

  * que las dos firmas reales se reconozcan como permanentes,
  * que un fallo TRANSITORIO no se marque —marcar de mas deja sin reintento a
    un fichero que si se habria recuperado, y eso lo pierde de verdad—,
  * que la marca sea idempotente: pulsar dos veces no debe apilar prefijos.
"""
import pytest

from src.routes.Webhook_bp import (
    _MARCA_IRRECUPERABLE,
    _marcar_irrecuperable,
    _motivo_irrecuperable,
)


class _FilaFalsa:
    """Lo minimo que `_marcar_irrecuperable` toca de una PodioFailedSync."""

    def __init__(self, error_message):
        self.error_message = error_message


class _SesionFalsa:
    def __init__(self):
        self.anadidas = []

    def add(self, obj):
        self.anadidas.append(obj)


# Los dos mensajes son literales de produccion, no inventados.
_410 = ("HTTPError: 410 Client Error: Gone for url: "
        "https://api.podio.com/file/2486162289")
_GRANDE = "BadRequest: File size too large. Got 18887334. Maximum is 10485760."


@pytest.mark.parametrize("mensaje, esperado", [
    (_410, "el fichero ya no existe en Podio"),
    (_GRANDE, "el fichero supera el tope de Cloudinary"),
])
def test_las_dos_firmas_reales_son_permanentes(mensaje, esperado):
    assert _motivo_irrecuperable(mensaje) == esperado


@pytest.mark.parametrize("mensaje", [
    # Un corte de red se arregla solo al reintentar.
    "ConnectionError: Connection aborted",
    # Podio caido: reintentar es exactamente lo que hay que hacer.
    "HTTPError: 502 Server Error: Bad Gateway for url: https://api.podio.com/file/1",
    "HTTPError: 503 Server Error: Service Unavailable",
    # La carrera que cerro el PR #146: el job aparece un segundo despues.
    "Error: Job con podio_item_id=3360843353 no existe en la BD",
    # Un 404 NO es un 410: el fichero puede no ser visible por permisos.
    "HTTPError: 404 Client Error: Not Found for url: https://api.podio.com/file/1",
    "",
    None,
])
def test_un_fallo_transitorio_nunca_se_marca(mensaje):
    """Marcar de mas es peor que marcar de menos: deja sin reintento algo que si
    se habria recuperado."""
    assert _motivo_irrecuperable(mensaje) is None


def test_marcar_deja_el_mensaje_original_dentro():
    """La fila es el unico inventario de que el fichero existio: el error
    original no se puede perder al etiquetarla."""
    fila = _FilaFalsa(_GRANDE)
    sesion = _SesionFalsa()

    assert _marcar_irrecuperable(sesion, fila, "el fichero supera el tope de Cloudinary")

    assert fila.error_message.startswith(_MARCA_IRRECUPERABLE)
    assert "el fichero supera el tope de Cloudinary" in fila.error_message
    assert _GRANDE in fila.error_message, "el error original tiene que sobrevivir"
    assert sesion.anadidas == [fila]


def test_marcar_dos_veces_no_apila_prefijos():
    """El barrido corre en CADA lectura del panel. Sin esto, el mensaje crecia
    un prefijo por visita hasta toparse con el corte de 2000 caracteres."""
    fila = _FilaFalsa(_410)
    sesion = _SesionFalsa()

    assert _marcar_irrecuperable(sesion, fila, "el fichero ya no existe en Podio")
    tras_la_primera = fila.error_message

    assert not _marcar_irrecuperable(sesion, fila, "el fichero ya no existe en Podio")
    assert fila.error_message == tras_la_primera
    assert fila.error_message.count(_MARCA_IRRECUPERABLE) == 1
    assert sesion.anadidas == [fila], "la segunda vez no debe tocar la sesion"


def test_una_fila_ya_marcada_sigue_siendo_irrecuperable():
    """El guard del resync se apoya en esto para no reintentar en la 2a pulsacion."""
    fila = _FilaFalsa(_410)
    _marcar_irrecuperable(_SesionFalsa(), fila, "el fichero ya no existe en Podio")

    assert _motivo_irrecuperable(fila.error_message) is not None


def test_el_mensaje_marcado_no_desborda_la_columna():
    """`error_message` es varchar y el modelo corta en 2000."""
    fila = _FilaFalsa("x" * 3000 + " File size too large. Got 1. Maximum is 0.")
    _marcar_irrecuperable(_SesionFalsa(), fila, "el fichero supera el tope de Cloudinary")

    assert len(fila.error_message) <= 2000


# ---------------------------------------------------------------------------
# Propagacion por fichero: el veredicto ya probado vale para el mismo file_id
# ---------------------------------------------------------------------------

class _FilaCompleta:
    """Doble con lo que mira `auto_marcar_irrecuperables`."""

    def __init__(self, id, error_message, file_ids, resolved=False):
        self.id = id
        self.error_message = error_message
        self.resolved = resolved
        self.payload = {"file_ids": file_ids, "action_type": "file_created"}


def _barrer(monkeypatch, filas):
    """Corre auto_marcar_irrecuperables contra una tabla falsa."""
    from contextlib import contextmanager
    import src.routes.Webhook_bp as wb

    class _Sesion:
        def __init__(self): self.commits = 0
        def exec(self, _stmt): return self
        def all(self): return filas
        def add(self, _o): pass
        def commit(self): self.commits += 1

    @contextmanager
    def _get_session():
        yield _Sesion()

    monkeypatch.setattr(wb, "get_session", _get_session)
    return wb.auto_marcar_irrecuperables()


def test_el_veredicto_se_propaga_al_mismo_fichero(monkeypatch):
    """El caso de produccion: la fila 15 llevaba el error VIEJO de la carrera,
    pero su fichero 2486162289 ya estaba probado muerto por la 22 (410 de
    Podio). Pedirle un Resync solo servia para redescubrirlo."""
    quince = _FilaCompleta(15, "Error: Job con podio_item_id=3356670474 no existe "
                               "en la BD; el adjunto no tiene donde colgar",
                           "2486162289")
    veintidos = _FilaCompleta(22, _410, "2486162289")

    assert _barrer(monkeypatch, [quince, veintidos]) == 2

    assert _MARCA_IRRECUPERABLE in quince.error_message
    assert "probado en la falla 22" in quince.error_message
    assert "no tiene donde colgar" in quince.error_message, "el error viejo sobrevive"


def test_no_se_propaga_a_un_fichero_distinto(monkeypatch):
    """La clave es el file_id. Otro fichero es otro caso, aunque el job coincida."""
    otra = _FilaCompleta(30, "Error: Job con podio_item_id=1 no existe en la BD",
                         "9999999")
    probada = _FilaCompleta(22, _410, "2486162289")

    assert _barrer(monkeypatch, [otra, probada]) == 1
    assert _MARCA_IRRECUPERABLE not in otra.error_message


def test_una_fila_con_un_fichero_sin_probar_conserva_su_resync(monkeypatch):
    """Con un solo fichero recuperable, el reintento aun puede salvar algo."""
    mixta = _FilaCompleta(31, "Error: Job con podio_item_id=1 no existe en la BD",
                          "2486162289,7777777")
    probada = _FilaCompleta(22, _410, "2486162289")

    assert _barrer(monkeypatch, [mixta, probada]) == 1
    assert _MARCA_IRRECUPERABLE not in mixta.error_message
