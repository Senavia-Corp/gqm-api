"""Un 5xx de Podio devolvia 200 y la entrega NO volvia jamas.

Dos piezas que se sumaban:

  * `_webhook_state_converged` para `item.update` solo comprobaba que el Job
    EXISTIERA. En un update sobre una fila que ya existia eso es trivialmente
    cierto pase lo que pase, incluso si el update no llego a aplicarse.
  * El atajo que la consulta se ejecutaba para CUALQUIER excepcion, no solo
    para las que tienen firma de carrera.

Resultado: un 5xx o un timeout de Podio -> 200 con note=duplicate_delivery ->
se salta el INSERT en la dead-letter -> y como Podio SOLO reintenta los 5xx, la
entrega no vuelve. Se perdian el upsert del job, las relaciones, los miembros,
los subcontratistas, las orders y las change orders.

`auto_resolver_convergidos` ya lo hacia bien comparando contra
`_ERRORES_DE_CARRERA`; era el atajo del webhook el que no miraba nada.
"""
from contextlib import contextmanager

import pytest
from sqlalchemy.exc import IntegrityError

import src.routes.Webhook_bp as wb


class _SesionFalsa:
    def __init__(self, hay_fila):
        self._hay = hay_fila

    def exec(self, _stmt):
        return self

    def first(self):
        return object() if self._hay else None


def _fingir_sesiones(monkeypatch, secuencia):
    restantes = list(secuencia)

    @contextmanager
    def falsa():
        yield _SesionFalsa(restantes.pop(0) if restantes else False)

    monkeypatch.setattr(wb, "get_session", falsa)
    monkeypatch.setattr(wb.time, "sleep", lambda *_: None)


# --------------------------------------------------------------------------
# La convergencia solo se afirma donde hay evidencia positiva
# --------------------------------------------------------------------------
def test_un_update_sobre_fila_preexistente_no_es_prueba_de_nada(monkeypatch):
    """EL AGUJERO.

    La fila existe (es un update sobre algo que ya estaba), asi que la
    comprobacion vieja decia True — y con ella un 5xx de Podio se cerraba con un
    200. Un update no deja evidencia positiva sin comparar campo a campo.
    """
    _fingir_sesiones(monkeypatch, [True, True, True])
    assert wb._webhook_state_converged("item.update", "123") is False, (
        "sigue dando por convergido un update solo porque la fila existe")


@pytest.mark.parametrize("evento", ["item.create", "item.delete"])
def test_create_y_delete_si_tienen_evidencia(monkeypatch, evento):
    """Regresion: estos dos si se pueden afirmar y deben seguir funcionando."""
    _fingir_sesiones(monkeypatch, [evento == "item.create"])
    assert wb._webhook_state_converged(evento, "123") is True


# --------------------------------------------------------------------------
# El atajo distingue una carrera de un fallo de verdad
# --------------------------------------------------------------------------
def _clasifica(error) -> bool:
    """Replica la decision del `except` del webhook sobre `error`."""
    return isinstance(error, IntegrityError) or any(
        p in str(error) for p in wb._ERRORES_DE_CARRERA)


@pytest.mark.parametrize("error", [
    IntegrityError("INSERT", {}, Exception("duplicate key")),
    Exception("duplicate key value violates unique constraint jobs_pkey"),
    Exception("StaleDataError: expected to update 1 row"),
])
def test_una_carrera_de_verdad_se_reconoce(error):
    assert _clasifica(error) is True


@pytest.mark.parametrize("error", [
    Exception("503 Server Error: Service Unavailable for url: api.podio.com"),
    Exception("HTTPSConnectionPool: Read timed out"),
    Exception("KeyError: 'fields'"),
    Exception("psycopg2.OperationalError: SSL connection has been closed"),
])
def test_un_fallo_de_verdad_no_se_disfraza_de_carrera(error):
    """Estos deben ir a dead-letter y 500 para que Podio REINTENTE."""
    assert _clasifica(error) is False, (
        f"un {error} se daria por entrega duplicada y no volveria nunca")


def test_el_webhook_condiciona_el_atajo_a_la_firma_del_error():
    """Regresion estructural: el atajo estaba dentro de un `except` pelado."""
    import ast
    import inspect
    import textwrap

    fuente = textwrap.dedent(inspect.getsource(wb.podio_jobs_webhook))
    codigo = ast.unparse(ast.parse(fuente))
    i = codigo.find("duplicate_delivery")
    assert i > 0, "desaparecio el atajo de entrega duplicada"

    previo = codigo[:i]
    assert "_ERRORES_DE_CARRERA" in previo, (
        "el atajo sigue sin mirar la firma del error: cualquier 5xx se cierra "
        "con un 200 y la entrega no vuelve")


# --------------------------------------------------------------------------
# Los tres silencios de file.change
# --------------------------------------------------------------------------
def test_hay_helper_con_sesion_propia_para_el_adjunto_sin_entidad():
    """`record_failed_sync` hace rollback() como PRIMERA instruccion.

    Llamarlo con la sesion viva del webhook se llevaria por delante el upsert
    del job y todo lo encolado de esa entrega. Por eso el helper abre la suya,
    igual que `record_failed_attachment`.
    """
    import ast
    import inspect
    import textwrap

    fn = wb._registrar_adjunto_sin_entidad
    codigo = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))

    assert "get_session()" in codigo, (
        "usa la sesion del llamador: el rollback() destruiria la entrega")
    assert "session" not in [a.arg for a in
                             ast.parse(textwrap.dedent(inspect.getsource(fn)
                                                       )).body[0].args.args]


@pytest.mark.parametrize("receptor", [
    "podio_jobs_webhook", "podio_general_webhook", "podio_relations_webhook"])
def test_un_adjunto_sin_entidad_deja_rastro(receptor):
    """Antes: `if entidad:` sin `else` (o un print). 200 y fichero perdido."""
    import ast
    import inspect
    import textwrap

    fn = getattr(wb, receptor)
    codigo = ast.unparse(ast.parse(
        textwrap.dedent(inspect.getsource(fn))))
    assert "_registrar_adjunto_sin_entidad" in codigo, (
        f"{receptor} sigue perdiendo el adjunto en silencio")
