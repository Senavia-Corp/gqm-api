from sqlmodel import select
from src.models.SubcontractorModel import Subcontractor
from src.models.ChangeOrderModel import ChangeOrder
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

        values = podio_fields.get(external_id)

        # Si no existe o está vacío
        if not values:
            return external_id

        if isinstance(values, list) and len(values) == 0:
            return external_id

    return None


# Encuentra el slot de acuerdo al subcontractor
def find_field_with_subc(
    job_type,
    podio_fields,
    subcontractor_podio_id
):

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config["order"]

    subcontractor_map = order_fields_map["ID_Subcontractor"]

    for index, field_id in subcontractor_map.items():

        values = podio_fields.get(field_id)

        if not values:
            continue

        for v in values:
            item_id = (
                v.get("value", {})
                 .get("item_id")
            )
            if item_id and str(item_id) == str(subcontractor_podio_id):
                return index

    return None


# Helper para encontrar tech_index
def resolve_tech_index_from_field(job_type: str, tech_field: str) -> int:

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config.get("order", {})

    formula_map = order_fields_map.get("Formula", {})

    for index, external_id in formula_map.items():
        if external_id == tech_field:
            return index

    # Si no es un field principal, tal vez sea un Change Order de ese tech
    order_co_map = field_config.get("order_co", {})
    for index, fields_list in order_co_map.items():
        if tech_field in fields_list:
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

    # ================= SUBCONTRACTOR =================
    if not order.ID_Subcontractor:
        raise Exception("Order requires a subcontractor")

    subcontractor = session.get(Subcontractor, order.ID_Subcontractor)

    if not subcontractor:
        raise Exception(f"Subcontractor {order.ID_Subcontractor} not found")

    if not subcontractor.podio_item_id:
        raise Exception("Subcontractor has no podio_item_id")

    # 🔥 1️⃣ Encontrar tech_index usando el subcontractor en Podio
    tech_index = find_field_with_subc(
        job_type,
        podio_job_fields,
        subcontractor.podio_item_id
    )

    if not tech_index:
        raise Exception("Subcontractor not linked to Job in Podio")

    # 🔥 2️⃣ Resolver Formula field
    formula_field = formula_map[tech_index]

    # Verificar si el formula_field primario ya está ocupado en Podio
    primary_values = podio_job_fields.get(formula_field)
    
    is_primary_taken = False
    if primary_values and (not isinstance(primary_values, list) or len(primary_values) > 0):
        is_primary_taken = True
        
    if is_primary_taken:
        raise Exception("El técnico ya tiene una orden principal creada. Edite la existente en lugar de crear una nueva.")
        
    assigned_field = formula_field
    is_co_field = False

    # 🔥 3️⃣ Guardar el campo asignado
    order.tech_field = assigned_field

    # ================= FORMULA =================
    if order.Formula is not None:
        fields_to_update[assigned_field] = float(order.Formula)

    # ================= PTL =================
    if not is_co_field:
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
def map_order_patch_to_podio(order, job_type, session, campos_tocados=None):
    """Campos de Podio a escribir por un PATCH de Order.

    Sobre `campos_tocados`: son las claves que el PATCH trajo de verdad
    (`model_dump(exclude_unset=True)`). Hacen falta para distinguir los dos
    casos que antes se confundian:

      * el campo NO viene en el PATCH  -> no se toca en Podio
      * el campo viene con None        -> hay que LIMPIARLO ([]), no callarse

    Antes solo se emitia el campo `if valor is not None`, asi que un None
    devolvia `{}`, la ruta hacia `if payload:` y SALTABA la llamada a Podio
    respondiendo 200. El valor quedaba NULL en la BD y el importe VIEJO intacto
    en Podio —que es la fuente de verdad—, sin fila en la dead-letter.

    No es teorico: el panel manda `ChangeOrderFormula: newFormula || null`
    (ChangeOrdersSection.tsx:324) y `newFormula` sale de `parseFloat(...) || 0`,
    asi que escribir 0 para limpiar manda `null` y dispara exactamente esto.

    Que es un bug lo prueba el propio fichero: el mapper de CREATE si escribe
    `[]` para limpiar, y el POST tiene un guard que devuelve 400.

    `campos_tocados=None` conserva el comportamiento antiguo para cualquier
    llamador que no lo pase.
    """
    if not order.tech_field:
        raise Exception("Order has no assigned Podio field")

    fields_to_update = {}

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config["order"]
    formula_map = order_fields_map.get("Formula", {})

    # 🔥 Resolver index automáticamente
    tech_index = resolve_tech_index_from_field(job_type, order.tech_field)

    is_co_field = order.tech_field not in formula_map.values()

    # ================= FORMULA =================
    if campos_tocados is None or "Formula" in campos_tocados:
        fields_to_update[order.tech_field] = (
            [] if order.Formula is None else float(order.Formula))

    # ================= PTL =================
    if not is_co_field:
        if "Ptl_hd_materials" in order_fields_map:
            if tech_index in order_fields_map["Ptl_hd_materials"]:
                hd_field = order_fields_map["Ptl_hd_materials"][tech_index]
    
                if campos_tocados is None or "Ptl_hd_materials" in campos_tocados:
                    valor_hd = getattr(order, "Ptl_hd_materials", None)
                    fields_to_update[hd_field] = (
                        [] if valor_hd is None else float(valor_hd))
    
        # ================= PAR =================
        if "Notes" in order_fields_map:
            notes_field = order_fields_map["Notes"][tech_index]
    
            if campos_tocados is None or "Notes" in campos_tocados:
                fields_to_update[notes_field] = order.Notes or []

    return fields_to_update


# ============ DELETE
def map_order_delete_to_podio(order, job_type, session=None):
    """Campos de Podio a limpiar al borrar una Order.

    `session` es opcional para no romper llamadores viejos, pero SIN ella no se
    puede comprobar si queda otra Order en el mismo slot — ver dentro.
    """

    if not order.tech_field:
        return {"fields": {}}

    fields_to_update = {}

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]
    order_fields_map = field_config["order"]
    formula_map = order_fields_map.get("Formula", {})

    # 🔥 Resolver index automáticamente
    tech_index = resolve_tech_index_from_field(job_type, order.tech_field)

    is_co_field = order.tech_field not in formula_map.values()

    # ¿QUEDA OTRA ORDER EN EL MISMO SLOT?
    #
    # Esto emitia `[]` a secas: borrar el campo en Podio. Y el slot
    # (job_podio_id, tech_field) puede tener MAS DE UNA Order — hoy mismo, en
    # produccion, el job 3304340068 (PAR6095) tiene ORD68994 y ORD69726 las dos
    # en `tech-1-ptl-original-pricing`. Borrando una, el campo se vaciaba en
    # Podio y el importe de la que SIGUE VIVA desaparecia de la fuente de
    # verdad.
    #
    # Con la superviviente se reescribe su formula en vez de limpiar. Sin
    # `session` no se puede mirar, y entonces se conserva el comportamiento
    # antiguo: es el caso del llamador que aun no la pasa.
    superviviente = None
    if session is not None:
        from src.models.OrderModel import Order

        superviviente = session.exec(
            select(Order).where(
                Order.job_podio_id == order.job_podio_id,
                Order.tech_field == order.tech_field,
                Order.ID_Order != order.ID_Order)
        ).first()

    # Formula
    if superviviente is not None and superviviente.Formula is not None:
        fields_to_update[order.tech_field] = float(superviviente.Formula)
    else:
        fields_to_update[order.tech_field] = []

    if not is_co_field:
        # PTL
        if "Ptl_hd_materials" in order_fields_map:
            if tech_index in order_fields_map["Ptl_hd_materials"]:
                hd_field = order_fields_map["Ptl_hd_materials"][tech_index]
                hd_vivo = getattr(superviviente, "Ptl_hd_materials", None)
                fields_to_update[hd_field] = (
                    [] if hd_vivo is None else float(hd_vivo))

        # PAR
        if "Notes" in order_fields_map:
            notes_field = order_fields_map["Notes"][tech_index]
            fields_to_update[notes_field] = (
                getattr(superviviente, "Notes", None) or [])

    return fields_to_update


# =================================================
# ------------ MAPPER DE CHANGE ORDER: ------------
# =================================================

# ============ POST
def map_chorder_create_to_podio(change_order, job_type, podio_job_fields, session):

    fields_to_update = {}
    candidate_fields = []

    field_config = JOB_TYPE_FIELD_REGISTRY[job_type]

    # 🔥 Determinar si es Project CO o Order CO
    if change_order.ID_Order:

        # ================= ORDER CHANGE ORDER =================
        if "order_co" not in field_config:
            return None

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
        if "project_co" not in field_config:
            return None

        project_co_map = field_config["project_co"]

        candidate_fields = list(project_co_map.values())

    # 1.5️⃣ Filtrar los campos que ya están tomados localmente
    taken_fields = session.exec(
        select(ChangeOrder.podio_field).where(
            ChangeOrder.job_podio_id == change_order.job_podio_id,
            ChangeOrder.podio_field.isnot(None),
            ChangeOrder.ID_ChangeOrder != change_order.ID_ChangeOrder
        )
    ).all()

    available_candidates = [f for f in candidate_fields if f not in taken_fields]

    # ====== Validación defensiva
    if not available_candidates:
        return None

    # 2️⃣ Buscar siguiente slot disponible
    available_field = find_next_available_field(
        podio_job_fields,
        available_candidates
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
def map_chorder_patch_to_podio(change_order, job_type, session,
                               campos_tocados=None):
    """Campos de Podio a escribir por un PATCH de Change Order.

    Sobre `campos_tocados`: son las claves que el PATCH trajo de verdad
    (`model_dump(exclude_unset=True)`). Hacen falta para distinguir los dos
    casos que antes se confundian:

      * el campo NO viene en el PATCH  -> no se toca en Podio
      * el campo viene con None        -> hay que LIMPIARLO ([]), no callarse

    Antes solo se emitia el campo `if valor is not None`, asi que un None
    devolvia `{}`, la ruta hacia `if payload:` y SALTABA la llamada a Podio
    respondiendo 200. El valor quedaba NULL en la BD y el importe VIEJO intacto
    en Podio —que es la fuente de verdad—, sin fila en la dead-letter.

    No es teorico: el panel manda `ChangeOrderFormula: newFormula || null`
    (ChangeOrdersSection.tsx:324) y `newFormula` sale de `parseFloat(...) || 0`,
    asi que escribir 0 para limpiar manda `null` y dispara exactamente esto.

    Que es un bug lo prueba el propio fichero: el mapper de CREATE si escribe
    `[]` para limpiar, y el POST tiene un guard que devuelve 400.

    `campos_tocados=None` conserva el comportamiento antiguo para cualquier
    llamador que no lo pase.
    """
    if not change_order.podio_field:
        raise Exception("Change Order has no assigned Podio field")

    fields_to_update = {}

    if campos_tocados is None or "ChangeOrderFormula" in campos_tocados:
        valor = change_order.ChangeOrderFormula
        fields_to_update[change_order.podio_field] = (
            [] if valor is None else float(valor))

    return fields_to_update


# ============ DELETE
def map_chorder_delete_to_podio(change_order, job_type):

    if not change_order.podio_field:
        return {}

    fields_to_update = {}

    # Limpiar el campo en Podio
    fields_to_update[change_order.podio_field] = []

    return fields_to_update
