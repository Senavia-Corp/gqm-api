from typing import Optional
import re
from .job_fields_map import FIELD_ALIASES_QID, FIELD_ALIASES_PTL, FIELD_ALIASES_PAR
from ..podio_job_extractor import get_job_field_value
from src.models.JobModel import JobBase
from src.utils.job_app_year import anio_desde_id_jobs


# ==========================================================================
# Qué significa "el campo no viene en el payload"
# ==========================================================================
# Podio OMITE del item los campos vacíos. Como `item_de_confianza` relee
# SIEMPRE el item entero de Podio antes de escribir (el `data["item"]` del
# cuerpo sólo se honra con APP_ENV=test), un campo ausente significa
# inequívocamente **vacío en Podio** — salvo por las dos excepciones de abajo.
#
# Hasta el 1-sep-2026 el mapeador se limitaba a saltarlo, así que vaciar un
# campo en Podio no lo vaciaba nunca en la BD: la fila se reescribía (subía
# `updated_at`, quedaba `Job updated from Podio` en tlactivity) conservando el
# valor viejo, indefinidamente y sin ninguna señal. Medido con QID61399 /
# `Additional_detail`: escribir "prueba entrega 2026-09-01" llegó; vaciarlo, no.

# EXCEPCIÓN 1 — la verdad no es Podio, es el recálculo local.
# `job_calculator.recalculate_job_fields` reconstruye estas columnas desde las
# órdenes. Vaciarlas aquí sería churn puro (el siguiente recálculo las vuelve a
# llenar) y además haría que `_diff_de_job` viera divergencia en todo job sin
# técnicos, plantando el cron de `reconciliar_dinero` contra su TOPE_CRON.
CAMPOS_CALCULADOS_EN_LOCAL = frozenset({
    "Estimated_rent", "Estimated_material", "Estimated_city", "Ptl_gc_fee",
    "Bldg_dept_fees", "Gqm_paid_fees", "Gqm_total_materials_fees",
    "Tech_formula_pricing", "Gqm_formula_pricing", "Gqm_adj_formula_pricing",
    "Gqm_total_change_orders", "Gqm_final_sold_pricing", "Acc_receivable",
    "Gqm_premium_in_money", "Gqm_target_return", "Gqm_final_form_pricing",
    "Gqm_final_adj_form_pricing", "Gqm_final_percentage",
    "Gqm_final_target_return", "Gqm_final_prem_in_money",
})

# EXCEPCIÓN 2 — el campo NO EXISTE en esa app-año, así que su ausencia no dice
# nada sobre si está vacío. Medido con un GET a las 12 apps reales el
# 2026-08-09: ~/outputs/gqm-entrega/reports/REG-073-mapper-vs-apps.md.
# Sólo se listan los que no cubre ya `CAMPOS_CALCULADOS_EN_LOCAL`; los de QID
# 2023/2024 (Gqm_paid_fees, Bldg_dept_fees) y PTL 2023/2024 (Acc_receivable)
# van repetidos a propósito, para que la tabla se lea entera contra el informe.
CAMPOS_SIN_EQUIVALENTE = {
    ("QID", 2023): frozenset({"Gqm_paid_fees", "Bldg_dept_fees"}),
    ("QID", 2024): frozenset({"Gqm_paid_fees", "Bldg_dept_fees"}),
    ("PTL", 2023): frozenset({"Acc_receivable"}),
    ("PTL", 2024): frozenset({"Acc_receivable"}),
    ("PTL", 2025): frozenset({"Estimated_completion_date", "Date_Received"}),
    ("PTL", 2026): frozenset({"Estimated_completion_date", "Date_Received"}),
    ("PAR", 2023): frozenset({"Pricing_target"}),
}

ALIASES_POR_TIPO = {
    "QID": FIELD_ALIASES_QID,
    "PTL": FIELD_ALIASES_PTL,
    "PAR": FIELD_ALIASES_PAR,
}


def campos_vaciables(job_type: str, anio) -> frozenset:
    """Las columnas que una ausencia en el payload SÍ puede poner a NULL.

    Fuente única a propósito: la usa el mapeador para decidir y la ruta
    `/admin/podio/obsoletos` para medir. Si cada uno tuviera su lista, la medida
    dejaría de decir nada sobre lo que el arreglo realmente hace.

    Sin año devuelve el conjunto vacío —no hay tabla de huecos que consultar—,
    que es el caso de los jobs sembrados por tests (`QID80001`) y de cualquier
    `ID_Jobs` que la regla del año no reconozca.
    """
    aliases = ALIASES_POR_TIPO.get(job_type)
    if aliases is None or anio is None:
        return frozenset()
    return (frozenset(aliases)
            - CAMPOS_CALCULADOS_EN_LOCAL
            - CAMPOS_SIN_EQUIVALENTE.get((job_type, anio), frozenset()))


# FASE 1: sin relaciones

# Extraer el Job_type desde el ID del proyecto
def extract_job_type_from_id(project_id: Optional[str]) -> Optional[str]:
    """
    Extrae el tipo de Job (QID, PTL, PAR) desde el ID del proyecto.
    Limpia etiquetas HTML como <p>QID51655</p> antes de procesar.
    """
    if not project_id:
        return None

    # Limpiar etiquetas HTML
    cleaned = re.sub(r"<.*?>", "", str(project_id)).strip().upper()

    if len(cleaned) < 3:
        return None

    prefix = cleaned[:3]
    if prefix in ("QID", "PTL", "PAR"):
        return prefix
    return None


# Mapeo de los datos de Podio a PostgreSQL
def map_podio_item_to_job(item: dict, session=None, job_type: Optional[str] = None) -> dict:
    """
    Transforma un item de Podio de QID, PTL o PAR para PostgreSQL.
    """

    fields = item.get("fields", [])

    app_item_id_formatted = item.get("app_item_id_formatted")

    if not job_type:
        job_type = extract_job_type_from_id(app_item_id_formatted)

    if not job_type:
        print(
            f"⚠️ No se pudo determinar job_type para item {app_item_id_formatted}")
        return {}

    # 🔑 Seleccionar aliases según tipo de job
    field_aliases = ALIASES_POR_TIPO.get(job_type)
    if field_aliases is None:
        return {}

    job_dict = {
        "podio_item_id": str(item.get("item_id")),
        "ID_Jobs": item.get("app_item_id_formatted"),
        "Job_type": job_type,
    }

    # Qué campos NO se pueden vaciar desde una ausencia. Sin año de app no se
    # puede consultar la tabla de huecos, así que ahí no se vacía nada: es el
    # caso de los jobs sembrados por tests (QID80001) y de cualquier ID que la
    # regla del año no reconozca.
    anio = anio_desde_id_jobs(app_item_id_formatted)
    no_vaciables = set(field_aliases) - campos_vaciables(job_type, anio)

    # Mapear dinámicamente usando aliases
    for db_field, field_cfg in field_aliases.items():
        value = get_job_field_value(fields, field_cfg)
        if value is not None:
            if isinstance(value, tuple):
                start, end = value
                job_dict[db_field] = start
                end_attr = f"{db_field}_end"
                if end_attr in JobBase.model_fields and (
                        end or db_field not in no_vaciables):
                    # sin `end` y con el campo vaciable, esto NULea la columna:
                    # borrar sólo la fecha de fin también es un vaciado.
                    job_dict[end_attr] = end
            else:
                job_dict[db_field] = value

        elif db_field in no_vaciables:
            print(
                f"[MAP WARN] {job_type} → {db_field} = no viene en este payload, se ignora")

        else:
            # Ausente = vacío en Podio. Se propaga el vaciado.
            job_dict[db_field] = None
            end_attr = f"{db_field}_end"
            if end_attr in JobBase.model_fields:
                job_dict[end_attr] = None

    return job_dict
