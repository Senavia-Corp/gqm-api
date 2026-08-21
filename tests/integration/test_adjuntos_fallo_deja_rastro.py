"""Un adjunto que falla tiene que DEJAR RASTRO, no desaparecer con un 200.

Antes de este arreglo, `src/utils/podio_webhook_core.py` tenia cuatro `except
Exception` que hacian `print` + `continue`. Cualquier fallo bajando el fichero
de Podio o subiendolo a Cloudinary perdia el fichero: no se escribia en
`podio_failed_syncs`, el webhook contestaba 200, y Podio NUNCA reenvia. El
fichero desaparecia sin que nadie se enterase.

Estos tests ejercitan el camino de verdad (monkeypatch de la subida), no
afirman sobre el texto del fuente. Con el codigo anterior FALLAN: no aparece
ninguna fila en `podio_failed_syncs`.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.AttachmentsModel import Attachments
from src.models.PodioFailedSyncModel import PodioFailedSync


def _limpiar(marca):
    with get_session() as s:
        for fila in s.exec(select(PodioFailedSync).where(
                PodioFailedSync.item_id == marca)).all():
            s.delete(fila)
        for att in s.exec(select(Attachments).where(
                Attachments.podio_file_id.like(f"{marca}%"))).all():
            s.delete(att)
        s.commit()


@pytest.fixture()
def marca():
    m = f"ZZT{uuid.uuid4().hex[:10]}"
    _limpiar(m)
    yield m
    _limpiar(m)


def test_un_fallo_de_cloudinary_deja_fila_en_failed_syncs(monkeypatch, marca):
    """El caso caro: Cloudinary revienta y el fichero se evapora."""
    from src.utils import podio_webhook_core as core

    monkeypatch.setattr(core, "get_podio_headers", lambda *a, **k: {})

    class RespFalsa:
        headers = {"Content-Type": "image/jpeg"}
        content = b"bytes-de-prueba"

        def raise_for_status(self):
            return None

        def json(self):
            return {"name": "prueba.jpg", "description": ""}

    monkeypatch.setattr(core.requests, "get", lambda *a, **k: RespFalsa())

    def subida_que_revienta(**kwargs):
        raise RuntimeError("Cloudinary caido (simulado)")

    monkeypatch.setattr(core, "upload_to_cloudinary", subida_que_revienta)

    file_id = f"{marca}001"
    with get_session() as s:
        core.process_file_change_event(
            s,
            {"action_type": "file_created", "file_ids": file_id,
             "item_id": marca},
            app_type="QID", year=2026, id_jobs=None,
            fk_field="ID_Jobs", fk_value="NO-EXISTE",
        )
        s.rollback()

    with get_session() as s:
        filas = s.exec(select(PodioFailedSync).where(
            PodioFailedSync.item_id == marca)).all()

    assert len(filas) == 1, (
        f"esperaba 1 fila en podio_failed_syncs, hay {len(filas)}. "
        "Con el `except` mudo original hay 0: el fichero se pierde en silencio."
    )
    fila = filas[0]
    assert fila.hook_type == "podio.attachment.file_created"
    assert fila.payload["file_id"] == file_id
    assert fila.resolved is False


def test_el_error_guardado_no_arrastra_sql_ni_parametros(monkeypatch, marca):
    """`error_message` no puede ser el volcado crudo de SQLAlchemy.

    Hoy `Webhook_bp.py` guarda `error_message=str(e)`, que en un IntegrityError
    arrastra `[SQL: INSERT ...] [parameters: {...}]` — y ese texto se sirve
    entero por `GET /webhook/podio/failed_syncs`. Con metadatos de adjuntos es
    inocuo; el dia que falle un INSERT sobre una tabla con una columna de
    token, ese token acaba literal en una fila y en una respuesta HTTP.
    """
    from src.utils import podio_webhook_core as core

    monkeypatch.setattr(core, "get_podio_headers", lambda *a, **k: {})

    def bajada_que_revienta(*a, **k):
        raise RuntimeError(
            "boom [SQL: INSERT INTO attachments ...] "
            "[parameters: {'secreto': 'no-deberia-persistirse'}]")

    monkeypatch.setattr(core.requests, "get", bajada_que_revienta)

    with get_session() as s:
        core.process_file_change_event(
            s,
            {"action_type": "file_created", "file_ids": f"{marca}002",
             "item_id": marca},
            app_type="QID", year=2026, id_jobs=None,
            fk_field="ID_Jobs", fk_value="NO-EXISTE",
        )
        s.rollback()

    with get_session() as s:
        fila = s.exec(select(PodioFailedSync).where(
            PodioFailedSync.item_id == marca)).first()

    assert fila is not None, "el fallo de descarga tampoco puede perderse"
    assert "[SQL:" not in fila.error_message
    assert "[parameters:" not in fila.error_message
    assert "no-deberia-persistirse" not in fila.error_message


def test_file_deleted_registra_sin_reventar_por_NameError(monkeypatch, marca):
    """Regresion: el `except` de file_deleted no puede lanzar NameError.

    `cloudinary_result` y `filename` solo se asignan en la rama file_created.
    Al instrumentar los otros dos `except` sin izarlas, el propio `except`
    lanzaba NameError — peor que el `print` que sustituia.
    """
    from src.utils import podio_webhook_core as core

    monkeypatch.setattr(core, "get_podio_headers", lambda *a, **k: {})

    def select_que_revienta(*a, **k):
        raise RuntimeError("fallo simulado en file_deleted")

    with get_session() as s:
        monkeypatch.setattr(s, "exec", select_que_revienta)
        core.process_file_change_event(
            s,
            {"action_type": "file_deleted", "file_ids": f"{marca}003",
             "item_id": marca},
            app_type="QID", year=2026, id_jobs=None,
            fk_field="ID_Jobs", fk_value="NO-EXISTE",
        )

    with get_session() as s:
        fila = s.exec(select(PodioFailedSync).where(
            PodioFailedSync.item_id == marca)).first()

    assert fila is not None, "file_deleted tambien tiene que dejar rastro"
    assert fila.hook_type == "podio.attachment.file_deleted"


def test_el_resync_no_miente_con_file_change(client, admin_headers, marca):
    """El boton Resync no puede decir "exitoso" sin haber hecho nada.

    `resync_failed_sync` entra en la rama de jobs cuando el hook_type es
    `podio.jobs.<app>.<year>.<event>`, pero dentro solo contempla
    item.create/item.update e item.delete. Con `file.change` NINGUN if
    coincidia y caia directo a `resolved = True` + "Resync exitoso".

    Rastro en produccion: los 12 registros de agosto son `file.change`, 7
    figuran resueltos, y los 12 ficheros seguian sin estar. Los updated_at de
    5 de ellos son 18:53:10, :12, :13, :14 y :16 del 14-ago — cinco clics,
    cinco "exitos", cero ficheros recuperados.
    """
    with get_session() as s:
        fila = PodioFailedSync(
            item_id=marca,
            hook_type="podio.jobs.QID.2026.file.change",
            payload={"file_ids": f"{marca}009", "type": "file.change"},
            error_message="fallo simulado",
        )
        s.add(fila)
        s.commit()
        s.refresh(fila)
        fila_id = fila.id

    resp = client.post(
        f"/webhook/podio/failed_syncs/{fila_id}/resync", headers=admin_headers)

    assert resp.status_code == 422, (
        f"esperaba 422, devolvio {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:200]}. Con el codigo anterior son 200 "
        f'y {{"message": "Resync exitoso"}} sin haber recuperado nada.'
    )

    with get_session() as s:
        despues = s.get(PodioFailedSync, fila_id)
        assert despues.resolved is False, (
            "un resync que no recupera nada NO puede marcar la fila como resuelta")
        s.delete(despues)
        s.commit()
