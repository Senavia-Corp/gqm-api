"""Vaciar un campo de texto de un job no puede tumbar la sincronización entera.

Contexto (1-sep-2026, QID61399 / item 3357171520). El panel guardaba `''` al
borrar el contenido de un campo, el mapeador lo convertía en `{"value": ""}` y
Podio devolvía 400 (`must be at least 1 characters long`). Como el sync es un
PUT del item completo, fallaba la actualización ENTERA del job: el cambio local
quedaba commiteado (REG-070) y el job divergía. Quedó en `podio_failed_syncs`
como `update_job_divergence` sin resolver.

Dos reglas, y este fichero es su gate:

1. Vacío = ausencia de dato. Ni `{"value": ""}` (400) ni `[]` (borra en Podio):
   la clave simplemente no aparece.
2. Borrar es un acto explícito y pasa por `limpiar_slots` — que hasta ahora era
   inerte para los campos escalares. Y sólo para texto: un `[]` en un `money`
   borra el importe (fix/patch-delete-no-borran-dinero) y en un `date` la fecha.
"""
import pytest

from src.models.JobModel import Job
from src.utils.mappers.to_podio.job_fields_map import external_ids_de
from src.utils.mappers.to_podio.par_mapper import map_job_to_podio_par
from src.utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from src.utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid


class _SesionVacia:
    """La sesión de producción para casi todos los jobs: no encuentra nada."""

    def exec(self, _statement):
        return self

    def first(self):
        return None

    def all(self):
        return []


@pytest.fixture
def sesion():
    return _SesionVacia()


def _vacios_literales(payload):
    """Las claves que Podio rechazaría con 400 por mandar una cadena vacía."""
    return sorted(k for k, v in payload.items() if v == {"value": ""})


# ------------------------------------------------- 1. el `''` no llega a Podio

def test_qid_texto_vacio_no_sale_como_cadena_vacia(sesion):
    job = Job(ID_Jobs="QID-TEST", Job_type="QID", Project_name="",
              Po_wtn_wo="", Additional_detail="")

    payload = map_job_to_podio_qid(job, session=sesion, year=2026)

    assert _vacios_literales(payload) == [], "Podio devolvería 400 y tumbaría el PUT entero"
    assert "project-name-2" not in payload
    assert "project-name" not in payload
    assert "superintendent" not in payload


def test_qid_location_vacia_tampoco(sesion):
    # `location` serializa igual que `text`: mismo 400.
    job = Job(ID_Jobs="QID-TEST", Job_type="QID", Project_location="")

    payload = map_job_to_podio_qid(job, session=sesion, year=2026)

    assert _vacios_literales(payload) == []
    assert "project-location" not in payload


@pytest.mark.parametrize("tipo, mapper, campos", [
    ("PTL", map_job_to_podio_ptl, {"Ptl_Superintendent": "", "Ptl_property_id": "",
                                   "Project_location": ""}),
    ("PAR", map_job_to_podio_par, {"Po_wtn_wo": ""}),
])
def test_ptl_y_par_texto_vacio_no_sale_como_cadena_vacia(tipo, mapper, campos, sesion):
    payload = mapper(Job(ID_Jobs=f"{tipo}-TEST", Job_type=tipo, **campos),
                     session=sesion, year=2026)

    assert _vacios_literales(payload) == []


def test_categoria_vacia_no_borra_el_campo_en_podio(sesion):
    # `''` es falsy: `convert_value_for_podio` devolvía `[]` para los tipos lista,
    # y `[]` en Podio BORRA. Es la fuga de agosto por la puerta del `''`.
    job = Job(ID_Jobs="QID-TEST", Job_type="QID", Job_status="", Service_type="")

    payload = map_job_to_podio_qid(job, session=sesion, year=2026)

    assert [k for k, v in payload.items() if v == []] == []
    assert "job-status" not in payload
    assert "service-type" not in payload


# ------------------------------------------- 2. el canal explícito ya funciona

def test_limpiar_slots_ahora_vacia_un_campo_de_texto(sesion):
    payload = map_job_to_podio_qid(
        Job(ID_Jobs="QID-TEST", Job_type="QID"), session=sesion, year=2026,
        limpiar_slots=["project-name-2"])

    assert payload["project-name-2"] == []
    # y no arrastra a los vecinos
    assert "project-name" not in payload
    assert "superintendent" not in payload


def test_sin_limpiar_slots_un_campo_sin_valor_no_se_toca(sesion):
    payload = map_job_to_podio_qid(
        Job(ID_Jobs="QID-TEST", Job_type="QID"), session=sesion, year=2026)

    assert "project-name-2" not in payload


# -------------------------------- 3. el filtro de tipo: sólo texto se puede vaciar

def test_external_ids_de_solo_deja_pasar_texto():
    assert external_ids_de("QID", ["Project_name", "Additional_detail",
                                   "Project_location"]) == [
        "project-name-2", "superintendent", "project-location"]


def test_external_ids_de_ignora_dinero_y_fechas():
    # Un `[]` en `gqm-target-sold-price` borraba el importe en Podio, y en
    # `date-received` la fecha. El panel manda `null` en esos campos al vaciarlos.
    assert external_ids_de("QID", ["Gqm_target_sold_pricing", "Date_assigned",
                                   "Estimated_rent", "Job_status",
                                   "Bldg_dept_fees", "Purchases_list"]) == []
    assert external_ids_de("PAR", ["Gqm_target_sold_pricing", "Date_assigned"]) == []


def test_external_ids_de_incluye_el_property_id_de_ptl():
    # `Ptl_property_id` mapea al external_id "title", que se excluyó por temor a que
    # fuese el título obligatorio del item. Medido contra Podio el 2-sep-2026: en la
    # app PTL de producción es `required=False` ("Property ID"), ya hay items con él
    # vacío, y un PUT con `{"title": []}` devolvió 200. Vaciarlo es legítimo.
    assert external_ids_de("PTL", ["Ptl_property_id"]) == ["title"]
    assert external_ids_de("PTL", ["Ptl_Superintendent", "Ptl_property_id"]) == [
        "superintendent", "title"]


def test_external_ids_de_no_conoce_las_relaciones_ni_lo_desconocido():
    assert external_ids_de("QID", ["ID_Client", "ID_BldgDept"]) == []
    assert external_ids_de("XXX", ["Project_name"]) == []
    assert external_ids_de("QID", ["campo_que_no_existe"]) == []


def test_pedir_vaciar_dinero_no_mete_ningun_borrado_en_el_payload(sesion):
    vaciados = ["Gqm_target_sold_pricing", "Date_assigned", "Estimated_rent"]

    payload = map_job_to_podio_qid(
        Job(ID_Jobs="QID-TEST", Job_type="QID"), session=sesion, year=2026,
        limpiar_slots=external_ids_de("QID", vaciados))

    assert [k for k, v in payload.items() if v == []] == []


# ------------------------------------------- 4. lo que sí tiene valor no cambia

def test_los_valores_reales_siguen_saliendo(sesion):
    job = Job(ID_Jobs="QID-TEST", Job_type="QID", Project_name="Casa 4",
              Project_location="Miami", Job_status="Invoiced",
              Gqm_target_sold_pricing=0.0)

    payload = map_job_to_podio_qid(job, session=sesion, year=2026)

    assert payload["project-name-2"] == {"value": "Casa 4"}
    assert payload["project-location"] == {"value": "Miami"}
    assert payload["job-status"] == [{"value": "Invoiced"}]
    # el cero es un dato, no un hueco
    assert payload["gqm-target-sold-price"] == {"value": "0", "currency": "USD"}
