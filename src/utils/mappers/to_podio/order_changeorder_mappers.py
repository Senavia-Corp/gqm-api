from src.models.SubcontractorModel import Subcontractor
from .order_changeorder_fields_map import (
    ORDER_QID_FIELDS,
    ORDER_PTL_FIELDS,
    ORDER_PAR_FIELDS,
    PROJECT_CO_QID_FIELDS,
    ORDER_CO_QID_FIELDS,
    PROJECT_CO_PTL_FIELDS,
    ORDER_CO_PTL_FIELDS
)
JOB_TYPE_FIELD_REGISTRY = {
    "QID": {
        "order": ORDER_QID_FIELDS,
        "project_co": PROJECT_CO_QID_FIELDS,
        "order_co": ORDER_CO_QID_FIELDS,
    },
    "PTL": {
        "order": ORDER_PTL_FIELDS,
        "project_co": PROJECT_CO_PTL_FIELDS,
        "order_co": ORDER_CO_PTL_FIELDS,
    },
    "PAR": {
        "order": ORDER_PAR_FIELDS
    }
}


# Función para buscar elsiguiente campo vacío:
def find_next_available_field(podio_fields: dict, candidate_fields: list[str]) -> str | None:
    """
    podio_fields: fields actuales del job en Podio
    candidate_fields: lista de external_ids posibles
    """

    for external_id in candidate_fields:

        field_value = podio_fields.get(external_id)

        # Si no existe o está vacío
        if not field_value:
            return external_id

    return None


# Helper para encontrar tech_index
def resolve_tech_index_from_field(job_type: str, tech_field: str) -> int:

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config["order"]

    formula_map = order_fields_map["Formula"]

    for index, external_id in formula_map.items():
        if external_id == tech_field:
            return index

    raise Exception(f"Tech index not found for field: {tech_field}")


# Convertir de lista a dict
def normalize_podio_fields(fields_list: list) -> dict:
    """
    Convierte la lista de fields de Podio en:
    {
        "external_id": values
    }
    """
    normalized = {}

    for field in fields_list:
        external_id = field.get("external_id")
        values = field.get("values", [])

        normalized[external_id] = values

    return normalized


# ==========================================
# ------------ MAPPER DE ORDER: ------------
# ==========================================

# ============ POST
def map_order_create_to_podio(order, job_type, podio_job_fields, session):

    fields_to_update = {}

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config["order"]

    formula_map = order_fields_map["Formula"]

    # 1️⃣ Buscar el primer Formula vacío
    available_field = find_next_available_field(
        podio_job_fields,
        list(formula_map.values())  # ← TODOS los slots posibles
    )

    if not available_field:
        raise Exception("No available technician slots in Podio")

    # 2️⃣ Guardar el external_id asignado
    order.tech_field = available_field

    # 3️⃣ Resolver automáticamente el índice
    tech_index = resolve_tech_index_from_field(job_type, available_field)

    # ================= FORMULA =================
    if order.Formula is not None:
        fields_to_update[available_field] = float(order.Formula)

    # ================= SUBCONTRACTOR =================
    subcontractor_external_id = order_fields_map["ID_Subcontractor"][tech_index]

    if order.ID_Subcontractor:
        subcontractor = session.get(Subcontractor, order.ID_Subcontractor)

        if not subcontractor:
            raise Exception(
                f"Subcontractor {order.ID_Subcontractor} not found")

        if not subcontractor.podio_item_id:
            raise Exception("Subcontractor has no podio_item_id")

        fields_to_update[subcontractor_external_id] = [
            int(subcontractor.podio_item_id)
        ]

    # ================= PTL =================
    if "Ptl_hd_materials" in order_fields_map:
        if tech_index in order_fields_map["Ptl_hd_materials"]:
            hd_field = order_fields_map["Ptl_hd_materials"][tech_index]

            if getattr(order, "Ptl_hd_materials", None) is not None:
                fields_to_update[hd_field] = float(order.Ptl_hd_materials)

    # ================= PAR =================
    if "Notes" in order_fields_map:
        notes_field = order_fields_map["Notes"][tech_index]

        if getattr(order, "Notes", None):
            fields_to_update[notes_field] = order.Notes

    return fields_to_update


# ============ PATCH
def map_order_patch_to_podio(order, job_type, session):

    if not order.tech_field:
        raise Exception("Order has no assigned Podio field")

    fields_to_update = {}

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config["order"]

    # 🔥 Resolver index automáticamente
    tech_index = resolve_tech_index_from_field(job_type, order.tech_field)

    # ================= FORMULA =================
    if order.Formula is not None:
        fields_to_update[order.tech_field] = float(order.Formula)
    else:
        fields_to_update[order.tech_field] = []

    # ================= SUBCONTRACTOR =================
    subcontractor_external_id = order_fields_map["ID_Subcontractor"][tech_index]

    if order.ID_Subcontractor is not None:

        if order.ID_Subcontractor == "":
            # limpiar campo
            fields_to_update[subcontractor_external_id] = []

        else:
            subcontractor = session.get(Subcontractor, order.ID_Subcontractor)

            if not subcontractor:
                raise Exception(
                    f"Subcontractor {order.ID_Subcontractor} not found"
                )

            if not subcontractor.podio_item_id:
                raise Exception(
                    "Subcontractor has no podio_item_id"
                )

            fields_to_update[subcontractor_external_id] = [
                int(subcontractor.podio_item_id)
            ]

    # ================= PTL =================
    if "Ptl_hd_materials" in order_fields_map:
        if tech_index in order_fields_map["Ptl_hd_materials"]:
            hd_field = order_fields_map["Ptl_hd_materials"][tech_index]

            if getattr(order, "Ptl_hd_materials", None) is not None:
                fields_to_update[hd_field] = float(order.Ptl_hd_materials)
            else:
                fields_to_update[hd_field] = []

    # ================= PAR =================
    if "Notes" in order_fields_map:
        notes_field = order_fields_map["Notes"][tech_index]

        if getattr(order, "Notes", None):
            fields_to_update[notes_field] = order.Notes
        else:
            fields_to_update[notes_field] = []

    return fields_to_update


# ============ DELETE
def map_order_delete_to_podio(order, job_type):

    if not order.tech_field:
        return {"fields": {}}

    fields_to_update = {}

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config["order"]

    # 🔥 Resolver index automáticamente
    tech_index = resolve_tech_index_from_field(job_type, order.tech_field)

    # Formula
    fields_to_update[order.tech_field] = []

    # Subcontractor
    subcontractor_external_id = order_fields_map["ID_Subcontractor"][tech_index]
    fields_to_update[subcontractor_external_id] = []

    # PTL
    if "Ptl_hd_materials" in order_fields_map:
        if tech_index in order_fields_map["Ptl_hd_materials"]:
            hd_field = order_fields_map["Ptl_hd_materials"][tech_index]
            fields_to_update[hd_field] = []

    # PAR
    if "Notes" in order_fields_map:
        notes_field = order_fields_map["Notes"][tech_index]
        fields_to_update[notes_field] = []

    return fields_to_update


# =================================================
# ------------ MAPPER DE CHANGE ORDER: ------------
# =================================================

# ============ POST
def map_chorder_create_to_podio(change_order, job_type, podio_job_fields, session):

    fields_to_update = {}

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]

    # 🔥 Determinar si es Project CO o Order CO
    if change_order.ID_Order:

        # ================= ORDER CHANGE ORDER =================

        if not change_order.order:
            raise Exception("Change Order has no associated Order")

        order = change_order.order

        if not order.tech_field:
            raise Exception("Associated Order has no tech_field assigned")

        # 1️⃣ Resolver tech_index
        tech_index = resolve_tech_index_from_field(
            job_type,
            order.tech_field
        )

        order_co_map = field_config["order_co"]

        if tech_index not in order_co_map:
            raise Exception("No Change Order config for this technician index")

        candidate_fields = order_co_map[tech_index]

    else:

        # ================= PROJECT CHANGE ORDER =================

        project_co_map = field_config["project_co"]

        candidate_fields = list(project_co_map.values())

    # 2️⃣ Buscar siguiente slot disponible
    available_field = find_next_available_field(
        podio_job_fields,
        candidate_fields
    )

    if not available_field:
        raise Exception("No available Change Order slots in Podio")

    # 3️⃣ Guardar el external_id asignado
    change_order.podio_field = available_field

    # 4️⃣ Construir payload
    if change_order.ChangeOrderFormula is not None:
        fields_to_update[available_field] = float(
            change_order.ChangeOrderFormula)
    else:
        fields_to_update[available_field] = []

    return fields_to_update


# ============ PATCH
def map_chorder_patch_to_podio(change_order, job_type, session):

    if not change_order.podio_field:
        raise Exception("Change Order has no assigned Podio field")

    fields_to_update = {}

    if change_order.ChangeOrderFormula is not None:
        fields_to_update[change_order.podio_field] = float(
            change_order.ChangeOrderFormula)
    else:
        fields_to_update[change_order.podio_field] = []

    return fields_to_update


# ============ DELETE
def map_chorder_delete_to_podio(change_order, job_type):

    if not change_order.podio_field:
        return {}

    fields_to_update = {}

    # Limpiar el campo en Podio
    fields_to_update[change_order.podio_field] = []

    return fields_to_update
