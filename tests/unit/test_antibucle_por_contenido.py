"""G4: el anti-bucle decide por contenido, no por reloj.

Antes descartaba cualquier evento de un ítem que la app hubiera tocado hace
menos de 15 s, así que **no distinguía el eco de la app de una edición humana**.
Reproducido en la auditoría: la app escribe, se esperan 3 s, alguien corrige un
campo en Podio → se perdía sin error, sin aviso y sin entrada en la cola de
fallos; el receptor respondía `200 {"status":"ignored"}`.
"""
import pytest

from src.utils.mappers import mapper_aux_functions as anti


@pytest.fixture(autouse=True)
def sin_memoria_previa(monkeypatch):
    monkeypatch.setattr(anti, "recent_events", {})
    # Aislado de la BD: estas pruebas fijan la LÓGICA, no la persistencia.
    monkeypatch.setattr(anti, "_huellas_recientes",
                        lambda item_id: [anti.recent_events[item_id][1:]]
                        if item_id in anti.recent_events else [])


def _item(campos, autor="app"):
    """`autor="app"` = escrito por token de aplicación (así escribe la app);
    `"user"` = alguien desde la interfaz de Podio."""
    return {"fields": [{"external_id": k, "values": [{"value": v}]}
                       for k, v in campos.items()],
            "current_revision": {"created_by": {"type": autor, "name": autor}}}


def test_el_eco_exacto_se_descarta():
    escrito = {"job-status": "Invoiced", "gqm-target-sold-price": 10000}
    anti.register_event("123", escrito)

    assert anti.is_recent_event("123", _item(escrito)) is True


def test_una_edicion_humana_en_otro_campo_SI_entra():
    """El caso que antes se perdía: la app escribe `job-status` y, dentro de la
    ventana, una persona toca `change-order-4`. El subconjunto que escribimos
    sigue coincidiendo, así que el contenido por sí solo no basta: lo decide
    quién firma la revisión."""
    anti.register_event("123", {"job-status": "Invoiced"})

    entrante = _item({"job-status": "Invoiced", "change-order-4": 11111}, autor="user")
    assert anti.is_recent_event("123", entrante) is False


def test_una_edicion_humana_sobre_el_mismo_campo_SI_entra():
    anti.register_event("123", {"job-status": "Invoiced"})

    assert anti.is_recent_event("123", _item({"job-status": "Hold"}, autor="user")) is False


def test_los_importes_de_podio_se_normalizan():
    """Podio devuelve '300.0000' donde la app escribió 300: sin normalizar, el
    eco de la propia app no se reconocería y volvería a entrar."""
    anti.register_event("123", {"bldg-fees-1": 300})

    assert anti.is_recent_event("123", _item({"bldg-fees-1": "300.0000"})) is True


def test_si_falta_uno_de_los_campos_escritos_no_es_el_eco():
    anti.register_event("123", {"bldg-fees-1": 100, "bldg-fees-2": 200})

    assert anti.is_recent_event("123", _item({"bldg-fees-1": 100})) is False


def test_un_item_de_otro_job_no_se_ve_afectado():
    anti.register_event("123", {"job-status": "Invoiced"})

    assert anti.is_recent_event("999", _item({"job-status": "Invoiced"})) is False


def test_la_ventana_ya_no_decide_por_si_sola():
    """La constante sigue existiendo como red, pero el criterio es el contenido."""
    assert anti.ANTI_LOOP_WINDOW >= 15
    anti.register_event("123", {"job-status": "Invoiced"})
    # mismo ítem, dentro de la ventana, editado por una persona → entra
    assert anti.is_recent_event("123", _item({"job-status": "Paid"}, autor="user")) is False


def test_una_edicion_humana_identica_tambien_entra():
    """Aunque el valor coincida por casualidad, si lo firma una persona no es
    nuestro eco."""
    anti.register_event("123", {"job-status": "Invoiced"})

    assert anti.is_recent_event(
        "123", _item({"job-status": "Invoiced"}, autor="user")) is False
