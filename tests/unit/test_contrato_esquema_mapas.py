"""Prueba de contrato: cada `external_id` que la app ESCRIBE existe en Podio.

Es la única defensa contra la deriva entre años, que es real y está medida
(auditoría 18-ago-2026, tomando 2026 como referencia):

    QID   2025: faltan 1 · 2024: faltan 13 · 2023: faltan 18
    PTL   2025: faltan 0 · 2024: faltan  3 · 2023: faltan  4
    PAR   2025: idéntica · 2024: faltan  7 · 2023: faltan 20

En concreto, las apps QID de 2023 y 2024 **no tienen** `bldg-fees-*`, así que en
esos jobs los BD Fees no pueden sincronizar en ninguna dirección.

La prueba corre **por año**, no sólo contra 2026, y separa dos cosas:

- **Escribir** en un campo que no existe da `field.not.found`: es un fallo duro,
  y por eso se comprueba con detalle.
- **Leer** un campo ausente sólo produce un aviso, así que el lector puede
  cubrir más años sin coste.

Los volcados viven fuera del repo (`~/outputs/gqm-auditoria-campos/esquema/`),
así que la prueba se salta sola donde no estén — pero deja constancia.
"""
import json
import pathlib

import pytest

ESQUEMA = pathlib.Path.home() / "outputs/gqm-auditoria-campos/esquema"
ANIOS = (2023, 2024, 2025, 2026)
TIPOS = ("QID", "PTL", "PAR")

pytestmark = pytest.mark.skipif(
    not ESQUEMA.exists(),
    reason=f"volcados de esquema no disponibles en {ESQUEMA}")


def _campos(tipo: str, anio: int) -> set[str]:
    f = ESQUEMA / f"{tipo.lower()}-{anio}-prod.json"
    if not f.exists():
        pytest.skip(f"sin volcado para {tipo} {anio}")
    return {c["external_id"] for c in json.loads(f.read_text())["campos"]}


def _slugs_del_job(tipo: str) -> set[str]:
    """Los `external_id` que el mapper de salida del job puede escribir."""
    from src.utils.mappers.to_podio import job_fields_map as m

    base = {"QID": m.BASE_QID_FIELDS, "PTL": m.BASE_PTL_FIELDS,
            "PAR": m.BASE_PAR_FIELDS}[tipo]
    salida = set()
    for config in base.values():
        if config.get("multi"):
            salida.update(config["external_ids"])
        else:
            salida.add(config["external_id"])
    return salida


# La deriva REAL, medida contra los volcados. No es cero, y fingir que lo es
# sería peor que documentarla: Podio rechaza la actualización ENTERA con
# `field.not.found` si el payload trae un campo que la app no tiene.
#
# Por eso `PodioBaseService._filtrar_por_anio` recorta el payload antes de
# enviarlo. Esta prueba fija la deriva conocida: si aparece una nueva, falla.
DERIVA_CONOCIDA = {
    ("QID", 2023): ["bldg-dept-fees-3", "bldg-fees-1", "bldg-fees-2",
                    "expected-completioninvoice", "project-name-2"],
    ("QID", 2024): ["bldg-dept-fees-3", "bldg-fees-1", "bldg-fees-2",
                    "expected-completioninvoice"],
    ("PAR", 2023): ["par-pricing-target"],
}


@pytest.mark.parametrize("tipo", TIPOS)
@pytest.mark.parametrize("anio", ANIOS)
def test_la_deriva_entre_anios_es_la_conocida(tipo, anio):
    """Un campo del mapa que no exista en esa app-año da `field.not.found`.

    QID 2023 y 2024 no tienen `bldg-fees-*`, así que en esos jobs los BD Fees
    no pueden sincronizar en ninguna dirección (REG-073).
    """
    faltan = sorted(_slugs_del_job(tipo) - _campos(tipo, anio))
    assert faltan == DERIVA_CONOCIDA.get((tipo, anio), []), (
        f"{tipo} {anio}: la deriva cambió → {faltan}")


@pytest.mark.parametrize("tipo, anio", sorted(DERIVA_CONOCIDA))
def test_el_filtro_por_anio_absorbe_la_deriva(tipo, anio):
    """Lo que no existe en esa app-año NO sale en el payload."""
    from src.podio.services.podio_base_services import PodioBaseService

    svc = PodioBaseService(tipo, "0", year=anio)
    payload = {s: 1 for s in _slugs_del_job(tipo)}
    quedan = set(svc._filtrar_por_anio(payload, "TEST"))
    assert not (quedan & set(DERIVA_CONOCIDA[(tipo, anio)]))
    assert quedan == _slugs_del_job(tipo) - set(DERIVA_CONOCIDA[(tipo, anio)])


@pytest.mark.parametrize("tipo", TIPOS)
@pytest.mark.parametrize("anio", ANIOS)
def test_las_relaciones_del_mapper_existen(tipo, anio):
    campos = _campos(tipo, anio)
    esperados = {"relationship"} | ({"bldg-dept"} if tipo == "QID" else set())
    faltan = sorted(esperados - campos)
    assert not faltan, f"{tipo} {anio}: faltan las relaciones {faltan}"


@pytest.mark.parametrize("tipo", TIPOS)
@pytest.mark.parametrize("anio", ANIOS)
def test_los_huecos_de_cuota_existen_en_esa_app(tipo, anio):
    """El mapa de cuotas se genera desde estos mismos volcados, así que esto
    detecta que el artefacto se haya quedado atrás."""
    from src.utils.mappers.from_podio import payment_slots

    if not payment_slots.habilitado(tipo):
        pytest.skip(f"{tipo} no usa cuotas parciales (decisión de cliente)")

    campos = _campos(tipo, anio)
    faltan = sorted({ext for cuotas in payment_slots.mapa_pagos(tipo, anio).values()
                     for ext in cuotas.values()} - campos)
    assert not faltan, f"{tipo} {anio}: huecos de cuota inexistentes: {faltan}"


@pytest.mark.parametrize("anio", ANIOS)
def test_los_huecos_de_orden_y_change_order_de_qid(anio):
    """Documenta la deriva de los técnicos altos en vez de esconderla.

    `tech-17-formula`..`tech-20-formula` EXISTEN en QID 2023 y el 17 en 2024,
    pero no en 2025/2026. Por eso el mapa NO se puede recortar a secas: hacerlo
    rompería 2023.
    """
    from src.utils.mappers.to_podio.order_changeorder_fields_map import ORDER_QID_FIELDS

    campos = _campos("QID", anio)
    faltan = sorted(set(ORDER_QID_FIELDS["Formula"].values()) - campos)
    esperado = {2023: [], 2024: ["tech-18-formula", "tech-19-formula", "tech-20-formula"]}
    if anio in esperado:
        assert faltan == esperado[anio]
    else:
        assert faltan == ["tech-17-formula", "tech-18-formula",
                          "tech-19-formula", "tech-20-formula"], (
            f"la deriva de {anio} cambió: {faltan}")


def test_qid_2023_y_2024_no_tienen_bd_fees():
    """REG-073, fijado como contrato: en esos años los BD Fees no pueden
    sincronizar en ninguna dirección, y el código debe tolerarlo con un aviso."""
    for anio in (2023, 2024):
        campos = _campos("QID", anio)
        assert "bldg-fees-1" not in campos, f"QID {anio} sí tendría bldg-fees-1"
