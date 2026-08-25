"""Un item.delete no puede borrar sin confirmar que el item ya no esta en Podio.

`event_delete` borraba la fila local buscando solo por `podio_item_id`, sin
comprobar nada. Y el endpoint acepta SIN autenticar mientras
PODIO_WEBHOOK_TOKEN no este configurada (medido el 20-ago-2026: POST
/webhook/podio/jobs/QID/2026 sin token devuelve 200, no 403; ningun hook de
produccion lleva token en la ruta).

Combinando las dos: cualquiera con la URL podia borrar jobs reales mandando
`{"type": "item.delete", "item_id": <cualquiera>}`.

Falla CERRADO: si el item sigue vivo NO se borra, y si la comprobacion no se
puede completar tampoco.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.utils import podio_webhook_core as core


class _Modelo:
    __name__ = "JobFalso"
    podio_item_id = "x"


def _sesion_con_objeto():
    s = MagicMock()
    s.exec.return_value.first.return_value = object()   # la fila local existe
    return s


@pytest.fixture(autouse=True)
def _select_neutralizado():
    """`_Modelo` no es un SQLModel, asi que select() lo rechaza. Lo que se prueba
    aqui es la DECISION de borrar o no, no la construccion de la consulta."""
    with patch.object(core, "select", return_value=MagicMock()):
        yield


def test_si_el_item_SIGUE_en_podio_no_se_borra():
    s = _sesion_con_objeto()
    with patch.object(core, "item_sigue_vivo_en_podio", return_value=True), \
         patch.object(core, "delete_with_retry") as borrar:
        core.event_delete(s, _Modelo, "3345393757", app_type="QID")
    borrar.assert_not_called()


def test_si_no_se_pudo_comprobar_tampoco_se_borra():
    """Podio caido o credenciales malas: preferimos una fila de mas que perder
    un job por un hipo de red."""
    s = _sesion_con_objeto()
    with patch.object(core, "item_sigue_vivo_en_podio", return_value=None), \
         patch.object(core, "delete_with_retry") as borrar:
        core.event_delete(s, _Modelo, "3345393757", app_type="QID")
    borrar.assert_not_called()


def test_si_el_item_YA_NO_esta_en_podio_si_se_borra():
    s = _sesion_con_objeto()
    with patch.object(core, "item_sigue_vivo_en_podio", return_value=False), \
         patch.object(core, "delete_with_retry") as borrar:
        core.event_delete(s, _Modelo, "3345393757", app_type="QID")
    borrar.assert_called_once()


def test_sin_fila_local_no_se_consulta_a_podio():
    """No gastar una llamada si no hay nada que borrar."""
    s = MagicMock()
    s.exec.return_value.first.return_value = None
    with patch.object(core, "item_sigue_vivo_en_podio") as comprobar:
        core.event_delete(s, _Modelo, "9999", app_type="QID")
    comprobar.assert_not_called()


@pytest.mark.parametrize("codigo,esperado", [
    (404, False), (410, False),
    # Podio responde 403 para items que NO existen, no 404: medido el
    # 18-ago-2026 con dos podio_item_id fabricados. Tratarlo como "no lo se"
    # bloqueaba borrados legitimos y rompia la sincronizacion de bajas.
    (403, False),
    (200, True), (201, True),
])
def test_lectura_de_los_codigos_de_podio(codigo, esperado):
    resp = MagicMock(status_code=codigo, ok=200 <= codigo < 300)
    with patch.object(core.requests, "get", return_value=resp), \
         patch.object(core, "get_podio_headers", return_value={}):
        assert core.item_sigue_vivo_en_podio(1, "QID") is esperado


@pytest.mark.parametrize("codigo", [500, 502, 429])
def test_un_5xx_no_autoriza_el_borrado(codigo):
    """Ahi el item probablemente sigue vivo y no se puede confirmar."""
    resp = MagicMock(status_code=codigo, ok=False)
    with patch.object(core.requests, "get", return_value=resp), \
         patch.object(core, "get_podio_headers", return_value={}):
        assert core.item_sigue_vivo_en_podio(1, "QID") is None


def test_un_error_de_red_devuelve_None_no_False():
    """None significa 'no lo se' y bloquea el borrado. False significa 'ya no
    esta' y lo permite: confundirlos borraria jobs cuando Podio falle."""
    with patch.object(core.requests, "get", side_effect=OSError("timeout")), \
         patch.object(core, "get_podio_headers", return_value={}):
        assert core.item_sigue_vivo_en_podio(1, "QID") is None


def test_la_cascada_no_acepta_que_le_olviden_el_app_type():
    """Guarda de regresion, ahora FUNCIONAL.

    Esto era `assert src.count("app_type=app_type") >= 3`: un assert TEXTUAL
    sobre el fuente. Contaba apariciones de una cadena, asi que pasaba con las
    tres en cualquier sitio —comentarios incluidos— y seguia pasando aunque el
    resync llamara sin app_type, que es justo lo que hacia en sus dos sitios.

    Sin `app_type` la confirmacion contra Podio no corre y el job se borra con
    toda su cascada sin preguntar. Ahora es un parametro obligatorio: olvidarlo
    revienta aqui en vez de borrar en silencio.
    """
    import inspect

    import src.routes.Webhook_bp as wb

    firma = inspect.signature(wb._cascade_delete_job_from_podio)
    app_type = firma.parameters["app_type"]

    assert app_type.default is inspect.Parameter.empty, (
        "app_type volvio a tener default: olvidarlo deja de ser un error")
    assert app_type.kind is inspect.Parameter.KEYWORD_ONLY, (
        "app_type deberia ir por nombre; posicional se cuela por accidente")

    with pytest.raises(TypeError):
        wb._cascade_delete_job_from_podio(object(), "123")
