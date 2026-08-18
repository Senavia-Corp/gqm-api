"""El cron escribe dinero sin nadie mirando. Los tests van sobre los frenos.

Existe porque la causa raíz no está arreglada: `PTL6035` volvió a desviarse dos
horas después de repararlo a mano. El cron acota el desvío a un día; no lo cura.
"""
import os

import pytest

from src.routes.podio_routes import Paridad

RUTA = "/admin/podio/reconciliar_cron"


@pytest.fixture
def sin_podio(monkeypatch):
    """Nada de red: si una guarda falla, el test lo dice sin llamar a Podio."""
    def _boom(*a, **k):
        raise AssertionError("no debería llegar a censar: una guarda falló")
    monkeypatch.setattr(Paridad, "_censo_y_diffs", _boom)


def test_sin_secreto_falla_cerrado(client, monkeypatch, sin_podio):
    """El token del webhook de Podio falló ABIERTO y dejó 45 hooks sin auth.

    Aquí no: sin `CRON_SECRET`, 503 y no se toca nada.
    """
    monkeypatch.delenv("CRON_SECRET", raising=False)
    r = client.get(f"{RUTA}?type=PTL")
    assert r.status_code == 503, r.get_data(as_text=True)[:200]


def test_secreto_incorrecto_es_401(client, monkeypatch, sin_podio):
    monkeypatch.setenv("CRON_SECRET", "el-bueno")
    r = client.get(f"{RUTA}?type=PTL", headers={"Authorization": "Bearer el-malo"})
    assert r.status_code == 401


def test_sin_cabecera_es_401(client, monkeypatch, sin_podio):
    monkeypatch.setenv("CRON_SECRET", "el-bueno")
    assert client.get(f"{RUTA}?type=PTL").status_code == 401


def test_tipo_invalido_es_400(client, monkeypatch, sin_podio):
    monkeypatch.setenv("CRON_SECRET", "s")
    r = client.get(f"{RUTA}?type=NOPE", headers={"Authorization": "Bearer s"})
    assert r.status_code == 400


def test_el_tope_impide_una_reescritura_masiva(client, monkeypatch):
    """Por encima del tope se planta SIN escribir.

    Si un día aparecen cientos de desvíos, algo cambió de fondo — un despliegue,
    un cambio de mapeo, una app reindexada — y reescribir a ciegas es peor que no
    hacer nada.
    """
    monkeypatch.setenv("CRON_SECRET", "s")
    monkeypatch.setattr(Paridad, "TOPE_CRON", 3)
    muchos = [{"ID_Jobs": f"PTL60{i:02d}", "cambios": {"Gqm_formula_pricing": {}},
               "_job": object()} for i in range(9)]
    monkeypatch.setattr(Paridad, "_censo_y_diffs",
                        lambda *a, **k: ([], muchos, []))

    escrituras = []
    monkeypatch.setattr(Paridad, "_aplicar",
                        lambda *a, **k: escrituras.append(1))

    r = client.get(f"{RUTA}?type=PTL", headers={"Authorization": "Bearer s"})
    assert r.status_code == 409
    d = r.get_json()
    assert d["aplicado"] is False
    assert d["jobs_desviados"] == 9
    assert not escrituras, "se escribió a pesar de superar el tope"


def test_un_censo_parcial_no_escribe(client, monkeypatch):
    """De media enumeración no se concluye nada — la app se movió."""
    monkeypatch.setenv("CRON_SECRET", "s")

    def _parcial(*a, **k):
        raise Paridad.CensoParcial("la app se movió")
    monkeypatch.setattr(Paridad, "_censo_y_diffs", _parcial)

    escrituras = []
    monkeypatch.setattr(Paridad, "_aplicar", lambda *a, **k: escrituras.append(1))

    r = client.get(f"{RUTA}?type=PTL", headers={"Authorization": "Bearer s"})
    assert r.status_code == 409
    assert r.get_json()["aplicado"] is False
    assert not escrituras


def test_dentro_del_tope_si_aplica(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s")
    monkeypatch.setattr(Paridad, "TOPE_CRON", 40)
    pocos = [{"ID_Jobs": "PTL6035", "cambios": {"Gqm_formula_pricing": {}},
              "_job": object()}]
    monkeypatch.setattr(Paridad, "_censo_y_diffs",
                        lambda *a, **k: ([1, 2, 3], pocos, []))

    escrituras = []
    monkeypatch.setattr(Paridad, "_aplicar", lambda s, d: escrituras.append(d))

    r = client.get(f"{RUTA}?type=PTL", headers={"Authorization": "Bearer s"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["aplicado"] is True and d["jobs_actualizados"] == 1
    assert d["ID_Jobs"] == ["PTL6035"]
    assert len(escrituras) == 1


def test_el_cron_solo_toca_el_anio_en_curso(client, monkeypatch):
    """Los años cerrados ya están reconciliados; si se mueven quiero enterarme,
    no que se arreglen solos y en silencio."""
    from datetime import datetime, timezone

    monkeypatch.setenv("CRON_SECRET", "s")
    vistos = []
    monkeypatch.setattr(Paridad, "_censo_y_diffs",
                        lambda ses, t, a, p: (vistos.append(a), ([], [], []))[1])
    monkeypatch.setattr(Paridad, "_aplicar", lambda *a, **k: None)

    client.get(f"{RUTA}?type=PTL", headers={"Authorization": "Bearer s"})
    assert vistos == [datetime.now(timezone.utc).year]


@pytest.mark.parametrize("metodo,ruta", [
    ("post", "/admin/podio/reconciliar_dinero?type=PTL&year=2026"),
    ("get", "/admin/podio/parity?type=PTL&year=2026"),
    ("post", "/admin/podio/purge_orphans?type=PTL&year=2026"),
    ("post", "/admin/podio/import?type=PTL&year=2026"),
])
def test_la_exencion_no_abre_el_resto_del_blueprint(client, metodo, ruta):
    """Eximir `reconciliar_cron` del RBAC no puede desproteger a sus vecinos.

    Comparten blueprint y prefijo `/admin/podio`, y tres de ellos escriben o
    borran. Si un refactor cambia el `overrides` por algo más ancho, esto salta.
    """
    r = getattr(client, metodo)(ruta)
    assert r.status_code == 401, (
        f"{ruta} respondió {r.status_code} sin credenciales — debería exigir JWT"
    )


def test_el_secreto_del_cron_no_sirve_para_las_demas(client, monkeypatch):
    """El secreto del cron no es una llave maestra del blueprint."""
    monkeypatch.setenv("CRON_SECRET", "s")
    r = client.post("/admin/podio/reconciliar_dinero?type=PTL&year=2026",
                    headers={"Authorization": "Bearer s"})
    assert r.status_code == 401, "el CRON_SECRET abrió una ruta que no le toca"


def test_vercel_json_declara_los_tres_crons():
    """Un tipo por invocación: QID del año en curso ronda los 1300 ítems y su
    enumeración se come casi los 300 s de la función."""
    import json
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    todos = json.loads((raiz / "vercel.json").read_text()).get("crons", [])
    # Filtrar por RUTA: vercel.json tambien declara crons de otras cosas (p. ej.
    # el refresco de tokens de QBO). Antes se afirmaba sobre la lista entera y
    # cualquier cron ajeno rompia este test sin que nada de Podio estuviera mal.
    crons = [c for c in todos if c["path"].startswith(RUTA)]
    tipos = {c["path"].split("type=")[-1] for c in crons}
    assert tipos == {"QID", "PTL", "PAR"}, f"faltan crons: {tipos}"
    # Escalonados: dos enumeraciones a la vez se pisan en la misma función.
    minutos = sorted(int(c["schedule"].split()[0]) for c in crons)
    assert len(set(minutos)) == 3, "los tres crons arrancan a la misma hora"
