"""No-regresión (1-sep-2026): vaciar un campo en Podio TIENE que vaciarlo en la BD.

Medido en producción con QID61399 (`podio_item_id` 3357171520) y el campo
`Additional_detail`: a las 20:36:37Z se escribió "prueba entrega 2026-09-01"
desde Podio y llegó; a las 20:39:25Z se vació desde Podio, la entrega se
procesó (subió `updated_at`, quedó `Job updated from Podio` en tlactivity) y la
BD siguió con el valor viejo. Podio omite del item los campos vacíos, y el
mapeador se limitaba a saltar lo ausente.

La otra mitad del contrato: **ausente no siempre es vacío**. Si el campo no
existe en esa app-año (REG-073) o si la columna la gobierna el recálculo local,
escribir NULL sería destruir un dato bueno.
"""
import pytest

from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from tests.fixtures.podio_items import date, par_item, ptl_item, qid_item, text


def _sin(item_dict, *external_ids):
    """El mismo item con esos campos borrados en Podio (= omitidos del payload)."""
    copia = dict(item_dict)
    copia["fields"] = [f for f in item_dict["fields"]
                       if f["external_id"] not in external_ids]
    return copia


# ------------------------------------------------------------------ vaciar

def test_campo_presente_y_luego_ausente_acaba_en_null():
    """El caso QID61399 exacto: `superintendent` → `Additional_detail`."""
    lleno = qid_item(tracking_id="QID61399")
    lleno["fields"].append(text("superintendent", "prueba entrega 2026-09-01"))

    assert map_podio_item_to_job(lleno)["Additional_detail"] == "prueba entrega 2026-09-01"

    vacio = map_podio_item_to_job(_sin(lleno, "superintendent"))
    assert "Additional_detail" in vacio, "el vaciado no se propaga: la BD se queda con el valor viejo"
    assert vacio["Additional_detail"] is None


@pytest.mark.parametrize("slugs, columna", [
    (("project-location",), "Project_location"),
    (("job-status",), "Job_status"),
    (("service-type",), "Service_type"),
    # Project_name tiene DOS alias (REG-072): hay que borrar los dos para que
    # el campo esté realmente vacío en Podio.
    (("project-name-2", "project-name"), "Project_name"),
])
def test_otros_campos_de_usuario_tambien_se_vacian(slugs, columna):
    mapeado = map_podio_item_to_job(_sin(qid_item(tracking_id="QID61399"), *slugs))
    assert mapeado[columna] is None


def test_vaciar_una_fecha_tambien_nulea_su_columna_end():
    """`date-received` trae (start, end); borrarlo debe limpiar las dos."""
    lleno = map_podio_item_to_job(qid_item(tracking_id="QID61399"))
    assert lleno["Date_assigned_end"] == "2026-08-02"

    vacio = map_podio_item_to_job(_sin(qid_item(tracking_id="QID61399"), "date-received"))
    assert vacio["Date_assigned"] is None
    assert vacio["Date_assigned_end"] is None


def test_borrar_solo_la_fecha_de_fin_nulea_el_end_y_deja_el_start():
    solo_inicio = qid_item(tracking_id="QID61399")
    solo_inicio["fields"] = [
        date("date-received", "2026-08-01") if f["external_id"] == "date-received" else f
        for f in solo_inicio["fields"]
    ]
    mapeado = map_podio_item_to_job(solo_inicio)
    assert mapeado["Date_assigned"] == "2026-08-01"
    assert mapeado["Date_assigned_end"] is None


# -------------------------------------------------------------- NO vaciar

@pytest.mark.parametrize("tipo, tracking, slug, columna", [
    # PTL 2025/2026 no tienen equivalente de Estimated_completion_date ni
    # Date_Received; PAR 2023 no tiene Pricing_target (REG-073, 2026-08-09).
    ("PTL", "PTL60123", "expected-completioninvoice", "Estimated_completion_date"),
    ("PAR", "PAR30123", "par-pricing-target", "Pricing_target"),
])
def test_campo_inexistente_en_esa_app_anio_no_se_pone_a_null(tipo, tracking, slug, columna):
    base = ptl_item(tracking_id=tracking) if tipo == "PTL" else par_item(tracking_id=tracking)
    mapeado = map_podio_item_to_job(_sin(base, slug))
    assert columna not in mapeado, (
        f"{tipo} {tracking}: {columna} no existe en esa app-año; su ausencia no "
        "dice que esté vacío y escribir NULL destruiría el dato")


def test_pero_en_una_app_anio_que_si_lo_tiene_ese_mismo_campo_se_vacia():
    """PTL 2023 sí tiene `Estimated_completion_date`; PTL 2026 no."""
    vacio_2023 = map_podio_item_to_job(
        _sin(ptl_item(tracking_id="PTL30123"), "expected-completioninvoice"))
    assert vacio_2023["Estimated_completion_date"] is None


@pytest.mark.parametrize("slug, columna", [
    ("gqm-formula-total-cost", "Gqm_formula_pricing"),
    ("calculation-10", "Gqm_paid_fees"),
    ("acc-receivable", "Acc_receivable"),
    ("estimated-material-total", "Estimated_material"),
])
def test_los_agregados_los_gobierna_el_recalculo_local_y_no_se_vacian(slug, columna):
    """`recalculate_and_apply` los reconstruye desde las órdenes.

    Vaciarlos sería churn, y además `_diff_de_job` vería divergencia en todo job
    sin técnicos y plantaría el cron de reconciliar_dinero contra TOPE_CRON.
    """
    mapeado = map_podio_item_to_job(_sin(qid_item(tracking_id="QID61399"), slug))
    assert columna not in mapeado


def test_sin_anio_de_app_no_se_vacia_nada():
    """QID80001 y demás sembrados por tests: sin año no hay tabla de huecos que
    consultar, así que se mantiene el comportamiento conservador."""
    mapeado = map_podio_item_to_job(_sin(qid_item(tracking_id="QID80001"), "superintendent"))
    assert "Additional_detail" not in mapeado


def test_ningun_agregado_calculado_sale_nunca_como_null():
    """La red de seguridad del recálculo: mapee lo que mapee un item parcial,
    ninguna columna que reconstruye `job_calculator` puede salir en NULL."""
    from src.utils.mappers.from_podio.job_mapper import CAMPOS_CALCULADOS_EN_LOCAL

    for base in (qid_item(tracking_id="QID61399"),
                 ptl_item(tracking_id="PTL60123"),
                 par_item(tracking_id="PAR60123")):
        mapeado = map_podio_item_to_job(base)
        nulos = {k for k, v in mapeado.items() if v is None}
        assert not (nulos & CAMPOS_CALCULADOS_EN_LOCAL), nulos & CAMPOS_CALCULADOS_EN_LOCAL
