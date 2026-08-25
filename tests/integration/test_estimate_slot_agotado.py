"""C1: el 4.º BD fee ya no se acepta para luego borrarse solo.

Corrida del 18-ago-2026. La app dejaba crear un cuarto coste `BDF` aprobado con
`201`, pero la app de Podio sólo tiene tres huecos. En cuanto **cualquier**
webhook tocaba el job —reproducido cambiando sólo `job-status`— el reconciliador
borraba el excedente: 4 filas BDF → 3, y `Estimated_city` de 1000 a 600.

Ahora la API lo rechaza antes de guardar nada, con el mismo contrato que los
change orders al agotar sus 11 huecos.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.EstimateCostModel import EstimateCost
from src.models.JobModel import Job


@pytest.fixture()
def job_id(client):
    jid = f"QIDSLOT{uuid.uuid4().int % 90000 + 10000}"
    with get_session() as s:
        s.add(Job(ID_Jobs=jid, Job_type="QID", podio_app_year=2026))
        s.commit()
    yield jid
    with get_session() as s:
        for r in s.exec(select(EstimateCost).where(EstimateCost.ID_Jobs == jid)).all():
            s.delete(r)
        j = s.exec(select(Job).where(Job.ID_Jobs == jid)).first()
        if j:
            s.delete(j)
        s.commit()


def _crear(client, admin_headers, jid, titulo, importe, estado="Approved", tipo="BDF"):
    return client.post("/estimate/", json={
        "ID_Jobs": jid, "Cost_type": tipo, "Status": estado,
        "Title": titulo, "Builder_cost": importe, "Client_price": importe,
    }, headers=admin_headers)


def _bdf(jid):
    with get_session() as s:
        return s.exec(
            select(EstimateCost)
            .where(EstimateCost.ID_Jobs == jid, EstimateCost.Cost_type == "BDF")
            .order_by(EstimateCost.ID_EstimateCost)).all()


def test_el_cuarto_bdf_aprobado_se_rechaza_y_no_crea_fila(client, admin_headers, job_id):
    for n, importe in enumerate([120, 240, 360], start=1):
        r = _crear(client, admin_headers, job_id, f"BD Fee {n}", importe)
        assert r.status_code == 201, r.get_json()

    r = _crear(client, admin_headers, job_id, "BD Fee 4 (desborde)", 480)

    assert r.status_code == 400
    assert r.get_json()["code"] == "no_available_slot"
    assert len(_bdf(job_id)) == 3, "no debe quedar ninguna fila del cuarto"


def test_los_tres_primeros_declaran_huecos_distintos(client, admin_headers, job_id):
    for n, importe in enumerate([120, 240, 360], start=1):
        assert _crear(client, admin_headers, job_id, f"BD Fee {n}", importe).status_code == 201

    huecos = [c.podio_field for c in _bdf(job_id)]
    assert huecos == ["bldg-fees-1", "bldg-fees-2", "bldg-dept-fees-3"]
    assert len(set(huecos)) == 3


def test_un_bdf_estimado_no_consume_hueco(client, admin_headers, job_id):
    """Regla de negocio V9: sólo los aprobados tocan los huecos de Podio."""
    for n in range(1, 4):
        assert _crear(client, admin_headers, job_id, f"BD Fee {n}", 100).status_code == 201

    r = _crear(client, admin_headers, job_id, "Cotizado", 999, estado="Estimated")
    assert r.status_code == 201
    assert r.get_json()["podio_field"] is None


def test_desaprobar_libera_el_hueco_y_otro_lo_reutiliza(client, admin_headers, job_id):
    ids = []
    for n, importe in enumerate([120, 240, 360], start=1):
        r = _crear(client, admin_headers, job_id, f"BD Fee {n}", importe)
        ids.append(r.get_json()["ID_EstimateCost"])

    # desaprobar el del medio suelta SU hueco, sin mover a los otros dos
    r = client.patch(f"/estimate/{ids[1]}", json={"Status": "Estimated"},
                     headers=admin_headers)
    assert r.status_code == 200

    por_id = {c.ID_EstimateCost: c.podio_field for c in _bdf(job_id)}
    assert por_id[ids[0]] == "bldg-fees-1"
    assert por_id[ids[1]] is None
    assert por_id[ids[2]] == "bldg-dept-fees-3", "el tercero no se mueve"

    # y ahora sí cabe uno nuevo, en el hueco liberado
    r = _crear(client, admin_headers, job_id, "BD Fee nuevo", 480)
    assert r.status_code == 201
    assert r.get_json()["podio_field"] == "bldg-fees-2"
