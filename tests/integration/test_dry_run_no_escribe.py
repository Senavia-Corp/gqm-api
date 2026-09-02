"""`PATCH /jobs/<id>?dry_run=true` no puede tocar la base.

Hasta ahora sí la tocaba: la ruta hacía `setattr` sobre el objeto de la sesión
(`Job.py`) y luego un `session.commit()` que quedaba FUERA del `if not dry_run`.
Se saltaba `save_with_retry`, las comisiones y la llamada a Podio, pero el body
de la petición quedaba persistido. Es la herramienta con la que se diagnostica
el sync, así que tiene que ser de verdad de sólo lectura.

De paso, este fichero es el gate de extremo a extremo del vaciado explícito:
un campo de texto presente en el body y vacío sale como `[]` (borrar en Podio),
y uno de dinero puesto a `null` NO — un `[]` ahí borraba el importe.
"""
import pytest
from sqlmodel import select

from src.models.JobModel import Job


@pytest.fixture()
def job_qid(client, admin_headers, db_session):
    """Un QID de usar y tirar en Neon develop, con y sin `podio_item_id`."""
    creados = []

    def _crear(con_item_podio=True, **campos):
        resp = client.post(
            "/jobs/",
            json={"Job_type": "QID", "Project_name": "Casa dry-run", **campos},
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)[:300]
        id_job = resp.get_json()["ID_Jobs"]
        creados.append(id_job)

        obj = db_session.exec(select(Job).where(Job.ID_Jobs == id_job)).first()
        # `ux_jobs_podio_item_id` es UNIQUE: derivarlo del ID del job, que ya lo es.
        obj.podio_item_id = (
            "999" + "".join(c for c in id_job if c.isdigit())) if con_item_podio else None
        db_session.add(obj)
        db_session.commit()
        return id_job

    yield _crear

    # Se borra por la ruta de la app, no con un DELETE a mano: `@audit` deja una
    # fila en `tlactivity` que referencia el job, y un delete directo choca con
    # la FK y deja el job vivo. Con post-condición, porque varios tests de esta
    # suite comprueban invariantes sobre TODOS los jobs de develop y un resto los
    # rompe tres ficheros más adelante, donde ya no se entiende por qué.
    for id_job in creados:
        resp = client.delete(f"/jobs/{id_job}", headers=admin_headers)
        assert resp.status_code in (200, 204, 404), \
            f"no se pudo limpiar {id_job}: {resp.get_data(as_text=True)[:200]}"
    db_session.expire_all()
    quedan = db_session.exec(
        select(Job.ID_Jobs).where(Job.ID_Jobs.in_(creados))).all()
    assert quedan == [], f"quedaron jobs de prueba en develop: {quedan}"


def _releer(db_session, id_job):
    db_session.expire_all()
    return db_session.exec(select(Job).where(Job.ID_Jobs == id_job)).first()


def test_dry_run_no_persiste_el_body(client, admin_headers, db_session, job_qid):
    id_job = job_qid()

    resp = client.patch(
        f"/jobs/{id_job}?sync_podio=true&dry_run=true&year=2026",
        json={"Project_name": ""},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["dry_run"] is True

    assert _releer(db_session, id_job).Project_name == "Casa dry-run", \
        "un dry_run escribió el body en la base"


def test_dry_run_muestra_el_borrado_explicito_del_texto(client, admin_headers, job_qid):
    id_job = job_qid()

    resp = client.patch(
        f"/jobs/{id_job}?sync_podio=true&dry_run=true&year=2026",
        json={"Project_name": ""},
        headers=admin_headers,
    )

    payload = resp.get_json()["podio_payload"]
    assert payload["project-name-2"] == [], "vaciar un texto debe pedir el borrado"
    assert {"value": ""} not in payload.values(), "Podio devolvería 400"


def test_un_campo_ausente_del_body_no_pide_borrado(client, admin_headers, job_qid):
    id_job = job_qid()

    resp = client.patch(
        f"/jobs/{id_job}?sync_podio=true&dry_run=true&year=2026",
        json={"Additional_detail": "una nota"},
        headers=admin_headers,
    )

    payload = resp.get_json()["podio_payload"]
    assert payload["project-name-2"] == {"value": "Casa dry-run"}
    assert [k for k, v in payload.items() if v == []] == [], \
        "sólo lo que el body pide vaciar puede salir como `[]`"


def test_vaciar_un_campo_de_dinero_no_borra_el_importe(client, admin_headers, job_qid):
    # Un `[]` en `gqm-target-sold-price` borraba el importe en Podio
    # (fix/patch-delete-no-borran-dinero). El panel manda `null` al vaciar el input.
    id_job = job_qid(Gqm_target_sold_pricing=1234.0)

    resp = client.patch(
        f"/jobs/{id_job}?sync_podio=true&dry_run=true&year=2026",
        json={"Gqm_target_sold_pricing": None},
        headers=admin_headers,
    )

    payload = resp.get_json()["podio_payload"]
    assert payload.get("gqm-target-sold-price") != []
    assert [k for k, v in payload.items() if v == []] == []


def test_dry_run_sin_podio_item_id_tampoco_escribe(client, admin_headers, db_session, job_qid):
    # Sin `podio_item_id` la petición no entra en el bloque de Podio y sale por
    # el `return` final: ese camino también tiene que descartar la transacción.
    id_job = job_qid(con_item_podio=False)

    resp = client.patch(
        f"/jobs/{id_job}?sync_podio=true&dry_run=true&year=2026",
        json={"Project_name": ""},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert _releer(db_session, id_job).Project_name == "Casa dry-run"
