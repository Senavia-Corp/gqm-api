"""El censo Podio ↔ BD. Pega a las apps TEST de verdad; nunca escribe.

Lo que estos tests protegen, por orden de importancia:

1. Que el endpoint **no pueda escribir** en Podio ni por accidente: el servicio
   que usa es de solo lectura.
2. Que en desarrollo **avise** de que los cuatro años comparten app (C4). Sin
   ese aviso el endpoint enseña un delta falso 3 de cada 4 veces y se pierde una
   tarde persiguiendo un hueco que no existe.
3. Que exija `admin:sync`: expone el mapa completo de app_ids de Podio.
"""
import pytest

from src.config import JOB_TYPES, JOB_YEARS


def test_exige_autenticacion(client):
    assert client.get("/admin/podio/parity").status_code in (401, 403)


def test_valida_los_parametros(client, admin_headers):
    assert client.get(
        "/admin/podio/parity?type=NOPE", headers=admin_headers).status_code == 400
    assert client.get(
        "/admin/podio/parity?year=2019", headers=admin_headers).status_code == 400


def test_la_sonda_devuelve_los_contadores_de_podio(client, admin_headers):
    resp = client.get("/admin/podio/parity?type=QID&year=2026", headers=admin_headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]

    cuerpo = resp.get_json()
    assert cuerpo["errores"] == [], cuerpo["errores"]
    fila = cuerpo["filas"][0]

    assert fila["podio"]["app_id"], "sin app_id no se puede auditar nada"
    assert fila["podio"]["filtered"] is not None, (
        "el paginador volvió a tirar `filtered`: sin él no hay censo")
    assert isinstance(fila["bd"]["por_anio"], int)
    assert isinstance(fila["bd"]["por_app_id"], int)


def test_avisa_de_que_en_dev_los_años_comparten_app(client, admin_headers):
    """C4: con APP_ENV=test las credenciales TAP se reutilizan para los 4 años.

    Sin este aviso, `?year=2023` y `?year=2026` consultan la MISMA app de Podio
    y devuelven el mismo total, mientras el lado BD sí se parte por año.
    """
    resp = client.get("/admin/podio/parity?type=QID&year=2025", headers=admin_headers)
    fila = resp.get_json()["filas"][0]

    assert fila["comparable_por_anio"] is False
    assert sorted(fila["apps_colapsadas"]) == sorted(JOB_YEARS)
    assert "app_id" in fila["nota"]


def test_todas_las_apps_de_un_tipo_apuntan_al_mismo_sitio_en_dev(client, admin_headers):
    """Corolario del anterior, medido: mismo app_id en los 4 años."""
    resp = client.get("/admin/podio/parity?type=PTL", headers=admin_headers)
    filas = resp.get_json()["filas"]

    assert len(filas) == len(JOB_YEARS)
    assert len({f["podio"]["app_id"] for f in filas}) == 1


def test_el_censo_completo_cubre_las_12_app_años(client, admin_headers):
    resp = client.get("/admin/podio/parity", headers=admin_headers)
    cuerpo = resp.get_json()

    assert len(cuerpo["filas"]) == len(JOB_TYPES) * len(JOB_YEARS)
    assert cuerpo["errores"] == [], cuerpo["errores"]


def test_enumerar_cuadra_la_sonda_con_la_paginacion(client, admin_headers):
    """Las dos medidas independientes tienen que coincidir. No se promedia."""
    resp = client.get(
        "/admin/podio/parity?type=QID&year=2026&enumerar=true", headers=admin_headers)
    fila = resp.get_json()["filas"][0]

    assert "inconsistente" not in fila, fila.get("inconsistente")
    assert fila["podio"]["enumerados"] == fila["podio"]["filtered"]
    for clave in ("faltan", "sobran", "desalineados"):
        assert clave in fila


def test_el_censo_usa_un_servicio_que_no_puede_escribir(monkeypatch):
    """La garantía estructural: aunque el código llamase a create_item, levanta."""
    from src.podio.services.podio_base_services import (
        EscrituraPodioBloqueada, PodioReadOnlyService)
    from src.routes.podio_routes import Paridad

    capturados = []
    original = Paridad.podio_jobs_router.get_readonly_service

    def _espiar(job_type, year):
        svc = original(job_type, year)
        capturados.append(svc)
        return svc

    monkeypatch.setattr(Paridad.podio_jobs_router, "get_readonly_service", _espiar)

    from src.database.db_sqlmodel import get_session
    with get_session() as s:
        Paridad._paridad_de_app(s, "QID", 2026, enumerar=False)

    assert capturados and all(isinstance(s, PodioReadOnlyService) for s in capturados)
    with pytest.raises(EscrituraPodioBloqueada):
        capturados[0].create_item({"x": 1})


def test_local_jobs_lista_los_que_nunca_llegaron_a_podio(client, admin_headers):
    resp = client.get("/admin/podio/local_jobs", headers=admin_headers)
    assert resp.status_code == 200

    cuerpo = resp.get_json()
    assert cuerpo["total"] == len(cuerpo["jobs"])
    assert all(j["ID_Jobs"] for j in cuerpo["jobs"])
