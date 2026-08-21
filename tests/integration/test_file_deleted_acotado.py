"""Un evento file_deleted de un job no puede borrar los adjuntos de OTRO.

DEFECTO QUE CUBRE: la rama `file_deleted` de `process_file_change_event`
buscaba el adjunto SOLO por `podio_file_id`, sin acotar a la entidad del
evento. Y `file_ids` viene del CUERPO de la peticion, sin validar.

Con la compuerta del webhook aun abierta, la cadena era:

  1. un `item_id` de job REAL (hay 7.625, y los podio_item_id son visibles
     en Podio)
  2. `file_ids` a eleccion de quien manda la peticion
  3. el SELECT casaba GLOBALMENTE
  4. borrado de Cloudinary Y de la BD

Con el id de UN job se podian borrar los 2.466 adjuntos del sistema. Y el
rastro enganaba: `log_activity` lo atribuye al usuario de Podio que figure en
la revision del item.

Este test reproduce exactamente ese cruce. Contra el codigo anterior FALLA.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.AttachmentsModel import Attachments
from src.models.JobModel import Job


@pytest.fixture()
def dos_jobs_con_adjunto():
    sfx = uuid.uuid4().int % 90000 + 10000
    d = {
        "job_a": f"QIDA{sfx}", "item_a": str(930000000 + sfx),
        "job_b": f"QIDB{sfx}", "item_b": str(940000000 + sfx),
        "att_a": f"ATTA{sfx}", "file_a": f"88{sfx}01",
        "att_b": f"ATTB{sfx}", "file_b": f"88{sfx}02",
    }
    with get_session() as s:
        s.add(Job(ID_Jobs=d["job_a"], Job_type="QID", podio_item_id=d["item_a"]))
        s.add(Job(ID_Jobs=d["job_b"], Job_type="QID", podio_item_id=d["item_b"]))
        s.add(Attachments(ID_Attachment=d["att_a"], ID_Jobs=d["job_a"],
                          podio_file_id=d["file_a"], Document_name="a.pdf"))
        s.add(Attachments(ID_Attachment=d["att_b"], ID_Jobs=d["job_b"],
                          podio_file_id=d["file_b"], Document_name="b.pdf"))
        s.commit()
    yield d
    with get_session() as s:
        for modelo, campo, vals in (
                (Attachments, "ID_Attachment", (d["att_a"], d["att_b"])),
                (Job, "ID_Jobs", (d["job_a"], d["job_b"]))):
            for v in vals:
                fila = s.exec(select(modelo).where(
                    getattr(modelo, campo) == v)).first()
                if fila:
                    s.delete(fila)
        s.commit()


def _existe(att_id):
    with get_session() as s:
        return s.exec(select(Attachments).where(
            Attachments.ID_Attachment == att_id)).first() is not None


def test_un_job_no_puede_borrar_el_adjunto_de_otro(monkeypatch, dos_jobs_con_adjunto):
    """El ataque: evento del job A, file_id del job B."""
    from src.utils import podio_webhook_core as core
    d = dos_jobs_con_adjunto

    # que no salga a Cloudinary de verdad
    monkeypatch.setattr(core, "delete_from_cloudinary", lambda *a, **k: None)
    monkeypatch.setattr(core, "get_podio_headers", lambda *a, **k: {})

    with get_session() as s:
        core.process_file_change_event(
            s,
            {"action_type": "file_deleted",
             "file_ids": d["file_b"],          # ← el fichero del OTRO job
             "item_id": d["item_a"]},
            app_type="QID", year=2026,
            id_jobs=d["job_a"],                 # ← el evento es del job A
        )
        s.commit()

    assert _existe(d["att_b"]), (
        "el adjunto del job B se borro con un evento del job A. Con la "
        "compuerta abierta, eso permite borrar CUALQUIER adjunto del sistema "
        "teniendo el id de un solo job.")
    assert _existe(d["att_a"]), "el del job A no se toco, no deberia faltar"


def test_el_borrado_legitimo_sigue_funcionando(monkeypatch, dos_jobs_con_adjunto):
    """Control positivo: acotar no puede impedir el borrado que SI toca."""
    from src.utils import podio_webhook_core as core
    d = dos_jobs_con_adjunto

    monkeypatch.setattr(core, "delete_from_cloudinary", lambda *a, **k: None)
    monkeypatch.setattr(core, "get_podio_headers", lambda *a, **k: {})

    with get_session() as s:
        core.process_file_change_event(
            s,
            {"action_type": "file_deleted",
             "file_ids": d["file_a"],          # ← su propio fichero
             "item_id": d["item_a"]},
            app_type="QID", year=2026,
            id_jobs=d["job_a"],
        )
        s.commit()

    assert not _existe(d["att_a"]), (
        "el borrado legitimo del propio adjunto del job dejo de funcionar")
    assert _existe(d["att_b"]), "y el del otro job sigue sin tocarse"
