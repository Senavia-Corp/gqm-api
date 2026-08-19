"""H4 y G6: reglas por tipo de job, y errores que dicen qué pasó.

H4 — `recalculate_job_fields` **nunca mira `Job_type`** (cero coincidencias en
el fichero), así que un alquiler o un BD fee metido en un PTL/PAR entraba en
`Gqm_formula_pricing` y no tenía destino en Podio: el precio de la app se
desviaba en silencio. Medido en la corrida del 18-ago-2026: PTL **+400**
(Rent 250 + BDF 150) y PAR **+900** (los tres conceptos, y ningún campo de
Podio cambió).

G6 — el rechazo de una segunda orden en el mismo hueco llegaba como
`500 {"code":"internal_error"}`: el mensaje real nunca alcanzaba al panel.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.EstimateCostModel import EstimateCost
from src.models.JobModel import Job


@pytest.fixture()
def jobs(client):
    """Un job de cada tipo, sin ítem de Podio (aquí sólo se prueban las reglas)."""
    sufijo = uuid.uuid4().int % 90000 + 10000
    ids = {t: f"{t}REGLA{sufijo}" for t in ("QID", "PTL", "PAR")}
    with get_session() as s:
        for tipo, jid in ids.items():
            s.add(Job(ID_Jobs=jid, Job_type=tipo, podio_app_year=2026))
        s.commit()
    yield ids
    with get_session() as s:
        for jid in ids.values():
            for e in s.exec(select(EstimateCost).where(EstimateCost.ID_Jobs == jid)).all():
                s.delete(e)
            j = s.exec(select(Job).where(Job.ID_Jobs == jid)).first()
            if j:
                s.delete(j)
        s.commit()


def _coste(client, headers, jid, tipo_coste, importe=100):
    return client.post("/estimate/", json={
        "ID_Jobs": jid, "Cost_type": tipo_coste, "Status": "Approved",
        "Title": f"{tipo_coste} de prueba", "Builder_cost": importe,
        "Client_price": importe}, headers=headers)


@pytest.mark.parametrize("tipo_job, tipo_coste", [
    ("PTL", "Rent"), ("PTL", "BDF"),
    ("PAR", "Rent"), ("PAR", "BDF"), ("PAR", "Material"),
    ("QID", "PTLGCF"),
])
def test_se_rechaza_el_coste_sin_destino_en_podio(client, admin_headers, jobs,
                                                  tipo_job, tipo_coste):
    r = _coste(client, admin_headers, jobs[tipo_job], tipo_coste)

    assert r.status_code == 422, r.get_json()
    assert r.get_json()["code"] == "cost_type_no_valido_para_el_tipo"

    with get_session() as s:
        assert not s.exec(select(EstimateCost).where(
            EstimateCost.ID_Jobs == jobs[tipo_job])).all()


@pytest.mark.parametrize("tipo_job, tipo_coste", [
    ("QID", "Rent"), ("QID", "BDF"), ("QID", "Material"),
    ("PTL", "Material"),        # PTL SÍ mapea material → `fees-and-cost`
    ("PTL", "PTLGCF"),
    ("PAR", "Subcontractor"),   # la mano de obra alimenta las órdenes
    ("QID", "Equipment"), ("QID", "Other"),
])
def test_los_costes_con_destino_siguen_pasando(client, admin_headers, jobs,
                                               tipo_job, tipo_coste):
    r = _coste(client, admin_headers, jobs[tipo_job], tipo_coste)
    assert r.status_code == 201, r.get_json()


def test_el_precio_de_la_app_ya_no_se_desvia(client, admin_headers, jobs):
    """El desvío medido en la corrida: PTL +400 por Rent+BDF."""
    antes = _formula(jobs["PTL"])
    _coste(client, admin_headers, jobs["PTL"], "Rent", 250)
    _coste(client, admin_headers, jobs["PTL"], "BDF", 150)
    assert _formula(jobs["PTL"]) == antes, "el rechazo evita el desvío"


def _formula(jid):
    with get_session() as s:
        j = s.exec(select(Job).where(Job.ID_Jobs == jid)).first()
        return float(j.Gqm_formula_pricing or 0)
