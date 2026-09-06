"""El anti-bucle no puede descartar un `file.change`.

`is_recent_event` existe para que una escritura NUESTRA a Podio no vuelva de
rebote como `item.update` y se reprocese. Pero se aplicaba a TODOS los
event_type, `file.change` incluido — y escribir un campo del job en Podio no
genera un evento de fichero.

Consecuencia medida por lectura del codigo: durante los 15 s de
`ANTI_LOOP_WINDOW` posteriores a cualquier escritura del API sobre un item, un
adjunto que alguien subiera en Podio se descartaba con un 200, sin fila en
`podio_failed_syncs` y sin reintento de Podio. Perdida silenciosa, del mismo
tipo que la carrera del adjunto sin job.

Con el codigo anterior el primer test FALLA: el `file.change` sale ignorado.
"""
import pytest
from flask import Flask

from src.utils.mappers.mapper_aux_functions import register_event
from src.utils.podio_webhook_core import parse_and_validate_webhook

app = Flask(__name__)


def _entregar(tipo, item_id):
    """Pasa un cuerpo de webhook por el parser y dice si lo ignoro."""
    with app.test_request_context(
            "/webhook/podio/jobs/QID/2026",
            data={"type": tipo, "item_id": str(item_id),
                  "action_type": "file_created", "file_ids": "111"}):
        _app_type, data, early, status = parse_and_validate_webhook("QID", 2026)
    ignorado = data is None and status == 200
    return ignorado


def test_un_adjunto_no_se_descarta_por_una_escritura_reciente():
    item = "3360843353"
    register_event(item)          # el API acaba de escribir en ese item

    assert not _entregar("file.change", item), (
        "el anti-bucle se comio un file.change. Un adjunto subido en los 15 s "
        "siguientes a una escritura del API se perdia con un 200, sin dejar "
        "fila en la dead-letter."
    )


def test_el_antibucle_sigue_parando_el_eco_de_item_update():
    """Lo que el anti-bucle SI tiene que seguir haciendo."""
    item = "3360837508"
    register_event(item)

    assert _entregar("item.update", item), (
        "el anti-bucle dejo pasar el eco de nuestra propia escritura: la guarda "
        "se abrio de mas y vuelve el bucle."
    )


@pytest.mark.parametrize("tipo", ["item.create", "item.delete"])
def test_los_demas_eventos_no_cambian(tipo):
    item = f"99{tipo.replace('.', '')}"
    register_event(item)
    assert _entregar(tipo, item)
