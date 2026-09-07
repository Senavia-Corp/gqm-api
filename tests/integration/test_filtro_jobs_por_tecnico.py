"""`GET /jobs?technicianId=…` filtra de verdad.

La ficha de técnico del panel pedía este filtro y el API **lo ignoraba en
silencio**: `Job.py` leía `subcontractorId` pero no tenía ningún filtro por
técnico —el que existe vive en otro blueprint, `/job_metrics/*`— así que la
respuesta traía TODOS los jobs. Medido antes del arreglo: `?technicianId=X`
devolvía los mismos 4 que sin filtro, para cualquier X, incluida una que no
existe.

Un parámetro que no se entiende y se ignora es peor que uno que se rechaza: la
respuesta parece correcta. Aquí llegó a producir «No jobs found» en una
pantalla que sí tenía filas en `job_technician`, y al arreglar el panel sin
mirar el API habría producido lo contrario —TODOS los jobs presentados como
asignados a ese técnico—, que es peor todavía.

Se comparan CONJUNTOS DE IDENTIFICADORES contra lo que dice `job_technician`,
no cantidades: un filtro que devolviera dos jobs equivocados daría el mismo
número que el correcto.
"""
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.link_models.JobTechnician import JobTechnicianLink


def _asignados_en_bd(technician_id):
    with get_session() as s:
        return {l.job_id for l in s.exec(
            select(JobTechnicianLink).where(
                JobTechnicianLink.technician_id == technician_id)).all()}


def _ids(resp):
    cuerpo = resp.get_json() or {}
    return {j.get("ID_Jobs") for j in (cuerpo.get("results") or [])}


def _tecnicos_con_asignaciones():
    with get_session() as s:
        return sorted({l.technician_id for l in s.exec(select(JobTechnicianLink)).all()})


def test_el_filtro_devuelve_exactamente_los_jobs_del_tecnico(client, admin_headers):
    tecnicos = _tecnicos_con_asignaciones()
    assert tecnicos, "sin filas en job_technician esta prueba no comprueba nada"

    for tid in tecnicos:
        resp = client.get(f"/jobs/?page=1&limit=200&technicianId={tid}",
                          headers=admin_headers)
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        esperado = _asignados_en_bd(tid)
        obtenido = _ids(resp)
        assert obtenido == esperado, (
            f"{tid}: el filtro devolvió {sorted(obtenido)} y la BD dice "
            f"{sorted(esperado)}")


def test_un_tecnico_sin_asignaciones_no_devuelve_nada(client, admin_headers):
    """El control que hace fallar a un filtro ignorado.

    Sin esto, un `?technicianId=` que no filtre dejaría verde la prueba de
    arriba en cuanto el técnico tuviera asignados TODOS los jobs de la base.
    """
    resp = client.get("/jobs/?page=1&limit=200&technicianId=NO-EXISTE-XYZ",
                      headers=admin_headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert _ids(resp) == set(), (
        "un técnico inexistente devuelve jobs: el filtro no se está aplicando")


def test_sin_filtro_siguen_saliendo_todos(client, admin_headers):
    """Y el control del control: que el filtro nuevo no recorte de más cuando
    no se pide."""
    con = client.get("/jobs/?page=1&limit=200&technicianId=NO-EXISTE-XYZ",
                     headers=admin_headers)
    sin = client.get("/jobs/?page=1&limit=200", headers=admin_headers)
    assert _ids(sin) > _ids(con), (
        "sin filtro no salen más jobs que con un filtro imposible")
