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
