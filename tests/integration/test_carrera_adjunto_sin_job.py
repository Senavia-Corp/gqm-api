"""El `file.change` tiene que esperar a que su `item.create` commitee.

`item.create` y `file.change` son hooks de Podio DISTINTOS: dos entregas HTTP
independientes, sin orden garantizado, y en Vercel cada una cae en otra lambda.
El alta de jobs ademas mete la fila en un savepoint y no commitea hasta el final
del handler. Resultado medido en produccion entre el 25-ago y el 3-sep-2026: 5
entregas de adjunto (14 ficheros) llegaron ANTES que su job, el receptor se
rindio al primer `select`, mando el fichero a la dead-letter y respondio 200 —
y Podio no reintenta los 2xx. El 5,8 % de las altas.

Desfases reales medidos: 327 ms, 506 ms, 642 ms, 1.168 ms y 4.904 ms.

Con el codigo anterior (`select` unico) el primer test de aqui FALLA: devuelve
None aunque el job aparezca 1,5 s despues.
"""
import threading
import time
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.routes.Webhook_bp import _esperar_entidad_del_adjunto


@pytest.fixture()
def ids():
    sfx = uuid.uuid4().int % 90000 + 10000
    d = {"job": f"QIDC{sfx}", "item": str(950000000 + sfx)}
    yield d
    with get_session() as s:
        fila = s.exec(select(Job).where(Job.ID_Jobs == d["job"])).first()
        if fila:
            s.delete(fila)
            s.commit()


def _insertar_job_tras(retardo, ids, errores):
    """Simula al `item.create` commiteando desde OTRA entrega/lambda."""
    def _hilo():
        try:
            time.sleep(retardo)
            with get_session() as s:
                s.add(Job(ID_Jobs=ids["job"], Job_type="QID",
                          podio_item_id=ids["item"], podio_app_year=2026))
                s.commit()
        except Exception as e:          # el assert vive en el hilo principal
            errores.append(e)
    return threading.Thread(target=_hilo, daemon=True)


def test_el_adjunto_espera_a_que_su_job_commitee(ids):
    """El caso de produccion: el job aparece 1,5 s despues del file.change."""
    errores = []
    hilo = _insertar_job_tras(1.5, ids, errores)

    with get_session() as sesion_del_request:
        # La sesion del request abre su transaccion ANTES de que el job exista,
        # igual que en el webhook real. Si el reintento no sondea en sesion
        # nueva, esto es justo lo que puede no ver el commit ajeno.
        assert sesion_del_request.exec(select(Job).where(
            Job.podio_item_id == ids["item"])).first() is None

        hilo.start()
        job = _esperar_entidad_del_adjunto(
            sesion_del_request, Job, ids["item"])

    hilo.join(timeout=10)
    assert not errores, f"el hilo del item.create fallo: {errores}"

    assert job is not None, (
        "el file.change se rindio antes de que su job commiteara. Con el "
        "`select` unico original esto es None y el adjunto acaba en la "
        "dead-letter con un 200 que Podio no reintenta."
    )
    assert job.ID_Jobs == ids["job"]


def test_no_espera_si_el_job_ya_esta(monkeypatch, ids):
    """El 94 % de las entregas: el job existe. No puede costar ni un sleep.

    Se afirma sobre las llamadas a `sleep`, no sobre el reloj: una sola consulta
    a Neon desde fuera de Vercel tarda ~0,3 s, mas que la primera espera del
    presupuesto (0,25 s), asi que medir tiempo de pared aqui mide la red.
    """
    with get_session() as s:
        s.add(Job(ID_Jobs=ids["job"], Job_type="QID",
                  podio_item_id=ids["item"], podio_app_year=2026))
        s.commit()

    dormidas = []
    monkeypatch.setattr("src.routes.Webhook_bp.time.sleep", dormidas.append)

    with get_session() as sesion_del_request:
        job = _esperar_entidad_del_adjunto(
            sesion_del_request, Job, ids["item"])

    assert job is not None and job.ID_Jobs == ids["job"]
    assert dormidas == [], (
        f"el camino feliz durmio {dormidas}: el reintento tiene que activarse "
        "solo cuando la entidad NO esta."
    )


def test_si_se_agota_el_presupuesto_devuelve_none(monkeypatch, ids):
    """Acotar la perdida no es sustituirla por silencio.

    Si el job nunca llega, el llamante tiene que seguir escribiendo la fila en
    `podio_failed_syncs`. Devolver algo que no sea None aqui romperia el unico
    inventario de lo que se pierde.
    """
    monkeypatch.setattr(
        "src.routes.Webhook_bp._ESPERAS_ADJUNTO_SIN_ENTIDAD", (0.01, 0.01))

    with get_session() as sesion_del_request:
        job = _esperar_entidad_del_adjunto(
            sesion_del_request, Job, ids["item"])

    assert job is None
