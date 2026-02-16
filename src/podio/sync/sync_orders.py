import re
from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.podio.services.job_services import podio_jobs_router
from src.utils.id_generator import generate_custom_id
from src.models.JobModel import Job
from src.models.OrderModel import Order
from src.models.SubcontractorModel import Subcontractor
from src.models.ChangeOrderModel import ChangeOrder
from src.utils.mappers.from_podio.order_changeorder_mapper import (
    TECH_FORMULA_FIELDS,
    TECH_ADJ_FORMULA_FIELDS,
    TECH_HD_MATERIALS_FIELDS,
    TECH_NOTES_FIELDS,
    PROJECT_CHANGE_ORDER_FIELDS,
    ORDER_CHANGE_ORDERS_FIELDS
)
from src.utils.mappers.mapper_aux_functions import has_html, clean_html

# ===============================
# ----------- FASE 1 -----------
# ===============================

# CREACION DE FUNCIONES PARA PARA INSERTAR ORDER,
# CHAGE ORDER Y CHANGE ORDER DE ORDER


# ----- ORDER:
def upsert_order(
    session,
    job,
    podio_item_id: str,
    subcontractor_id: str,
    tech_index: int,
    formula: float,
    adj_formula: float,
    tech_field: str,
    hd_materials: float,
    hd_materials_field: str,
    notes: str,
    notes_field: str,
    dry_run: bool
):

    existing_order = session.exec(
        select(Order).where(
            Order.job_podio_id == podio_item_id,
            Order.tech_field == tech_field
        )
    ).first()

    if existing_order:

        changed = False

        if existing_order.Formula != formula:
            existing_order.Formula = formula
            changed = True

        if existing_order.Adj_formula != adj_formula:
            existing_order.Adj_formula = adj_formula
            changed = True

        if existing_order.ID_Subcontractor != subcontractor_id:
            existing_order.ID_Subcontractor = subcontractor_id
            changed = True

        if existing_order.Ptl_hd_materials != hd_materials:
            existing_order.Ptl_hd_materials = hd_materials
            changed = True

        if existing_order.hd_materials_field != hd_materials_field:
            existing_order.hd_materials_field = hd_materials_field
            changed = True

        if existing_order.Notes != notes:
            existing_order.Notes = notes
            changed = True

        if existing_order.notes_field != notes_field:
            existing_order.notes_field = notes_field
            changed = True

        if changed and not dry_run:
            session.add(existing_order)

        return existing_order, False  # False = no creado

    # 🔥 Generar ID
    prefix = "ORD"
    new_id = generate_custom_id(
        session,
        Order,
        "ID_Order",
        prefix
    )

    new_order = Order(
        ID_Order=new_id,
        Formula=formula,
        Adj_formula=adj_formula,
        job_podio_id=podio_item_id,
        tech_field=tech_field,
        Ptl_hd_materials=hd_materials,
        hd_materials_field=hd_materials_field,
        Notes=notes,
        notes_field=notes_field,
        ID_Subcontractor=subcontractor_id
    )

    if not dry_run:
        session.add(new_order)
        session.flush()

    return new_order, True  # True = creado


# -----  CHANGE ORDER:
def upsert_change_order(
    session,
    job,
    podio_item_id: str,
    podio_field: str,
    change_formula: float,
    order=None,
    dry_run: bool = False
):
    """
    Crea o actualiza un ChangeOrder.

    - Si order=None → Change Order nivel proyecto
    - Si order!=None → Change Order nivel Order
    """

    existing = session.exec(
        select(ChangeOrder).where(
            ChangeOrder.job_podio_id == podio_item_id,
            ChangeOrder.podio_field == podio_field
        )
    ).first()

    if existing:

        changed = False

        if existing.ChangeOrderFormula != change_formula:
            existing.ChangeOrderFormula = change_formula
            changed = True

        # 👇 Asegura que la relación esté correcta
        if order:
            if existing.ID_Order != order.ID_Order:
                existing.ID_Order = order.ID_Order
                changed = True
        else:
            if existing.ID_Order is not None:
                existing.ID_Order = None
                changed = True

        if changed and not dry_run:
            session.add(existing)

        return existing, False

    # 🔹 Crear nuevo

    # 🔥 Generar ID
    prefix = "ChO"
    new_id = generate_custom_id(
        session,
        ChangeOrder,
        "ID_ChangeOrder",
        prefix
    )

    new_co = ChangeOrder(
        ID_ChangeOrder=new_id,
        ChangeOrderFormula=change_formula,
        ID_Jobs=job.ID_Jobs,
        ID_Order=order.ID_Order if order else None,
        podio_field=podio_field,
        job_podio_id=podio_item_id
    )

    if not dry_run:
        session.add(new_co)

    return new_co, True


# EXTRAER SUBCONTRACTOR PARA CREAR RELACIÓN CON ORDER
def extract_subcontractor_from_field(session, field):
    """
    Extrae el Subcontractor desde technician-x
    """

    values = field.get("values", [])
    if not values:
        return None

    podio_related_id = values[0].get("value", {}).get("item_id")
    if not podio_related_id:
        return None

    subcontractor = session.exec(
        select(Subcontractor).where(
            Subcontractor.podio_item_id == str(podio_related_id)
        )
    ).first()

    return subcontractor


# ===============================
# ----------- FASE 2 -----------
# ===============================
# Viene desde las apps de Jobs
@retry_db(max_retries=3, delay=1)
def sync_job_orders_and_change_orders(
    job_type: str,
    year: int,
    limit: int = 30,
    offset: int = 0,
    dry_run: bool = False
):

    service = podio_jobs_router.get_service(
        job_type=job_type,
        year=year
    )

    items = service.get_items(limit=limit, offset=offset)

    if not items:
        return {"processed": 0}

    with get_session() as session:

        for item in items:

            fields = item.get("fields", [])
            podio_item_id = str(item.get("item_id"))

            job = session.exec(
                select(Job).where(
                    Job.podio_item_id == podio_item_id
                )
            ).first()

            if not job:
                continue

            tech_data = {}
            order_change_data = {}
            tech_counter = 0

            formula_map = TECH_FORMULA_FIELDS.get(job_type, {})
            adj_map = TECH_ADJ_FORMULA_FIELDS.get(job_type, {})
            hd_map = TECH_HD_MATERIALS_FIELDS.get(job_type, {})
            notes_map = TECH_NOTES_FIELDS.get(job_type, {})
            project_changeor_map = PROJECT_CHANGE_ORDER_FIELDS.get(
                job_type, {})
            order_change_orders_map = ORDER_CHANGE_ORDERS_FIELDS.get(
                job_type, {})

            # -----------------------------
            # 1️⃣ PARSEAR FIELDS
            # -----------------------------

            for f in fields:

                external_id = f.get("external_id")
                values = f.get("values", [])

                if not external_id or not values:
                    continue

                value = values[0].get("value")

                # -------- TECH SUBCONTRACTOR (App Field) --------
                if external_id.startswith("technician"):
                    tech_counter += 1
                    tech_index = tech_counter

                    subcontractor = extract_subcontractor_from_field(
                        session, f)

                    if subcontractor:
                        tech_data.setdefault(tech_index, {})
                        tech_data[tech_index]["subcontractor_id"] = subcontractor.ID_Subcontractor
                        tech_data[tech_index]["tech_field"] = external_id

                    continue

                # -------- TECH FORMULA --------
                matched = False
                for tech_index, field_ids in formula_map.items():

                    if external_id in field_ids:
                        tech_data.setdefault(tech_index, {})
                        tech_data[tech_index]["formula"] = value
                        tech_data[tech_index]["formula_field"] = external_id
                        matched = True
                        break

                if matched:
                    continue

                # -------- TECH ADJ --------
                matched = False
                for tech_index, field_ids in adj_map.items():

                    if external_id in field_ids:
                        tech_data.setdefault(tech_index, {})
                        tech_data[tech_index]["adj_formula"] = value
                        matched = True
                        break

                if matched:
                    continue

                # -------- TECH HD MATERIALS --------
                matched = False
                for tech_index, field_ids in hd_map.items():

                    if external_id in field_ids:
                        tech_data.setdefault(tech_index, {})
                        tech_data[tech_index]["hd_materials"] = value
                        tech_data[tech_index]["hd_materials_field"] = external_id
                        matched = True
                        break

                if matched:
                    continue

                # -------- TECH NOTES --------
                matched = False
                for tech_index, field_ids in notes_map.items():

                    if external_id in field_ids:
                        clean_value = clean_html(
                            value) if has_html(value) else value
                        tech_data.setdefault(tech_index, {})
                        tech_data[tech_index]["notes"] = clean_value
                        tech_data[tech_index]["notes_field"] = external_id
                        matched = True
                        break

                if matched:
                    continue

                # -------- PROJECT CHANGE ORDERS --------
                matched = False
                for tech_index, field_ids in project_changeor_map.items():

                    if external_id in field_ids:
                        tech_data.setdefault(tech_index, {})
                        tech_data[tech_index]["change_formula"] = value
                        tech_data[tech_index]["change_field"] = external_id
                        matched = True
                        break

                if matched:
                    continue

                # -------- ORDER CHANGE ORDERS --------
                matched = False
                for tech_index, field_ids in order_change_orders_map.items():

                    if external_id in field_ids:
                        order_change_data.setdefault(tech_index, {})
                        order_change_data[tech_index][external_id] = value
                        matched = True
                        break

                if matched:
                    continue

            # -----------------------------
            # 2️⃣ UPSERT ORDERS
            # -----------------------------

            orders_map = {}

            for tech_index, data in tech_data.items():

                formula = data.get("formula")
                adj_formula = data.get("adj_formula")
                subcontractor_id = data.get("subcontractor_id")
                tech_field = data.get("formula_field")
                hd_materials = data.get("hd_materials")
                hd_materials_field = data.get("hd_materials_field")
                notes = data.get("notes")
                notes_field = data.get("notes_field")

                order, created = upsert_order(
                    session=session,
                    job=job,
                    podio_item_id=podio_item_id,
                    subcontractor_id=subcontractor_id,
                    tech_index=tech_index,
                    formula=formula,
                    adj_formula=adj_formula,
                    tech_field=tech_field,
                    hd_materials=hd_materials,
                    hd_materials_field=hd_materials_field,
                    notes=notes,
                    notes_field=notes_field,
                    dry_run=dry_run
                )

                orders_map[tech_index] = order

            # -----------------------------
            # 3️⃣ UPSERT PROJECT CHANGE ORDERS
            # -----------------------------
            for tech_index, data in tech_data.items():

                change_formula = data.get("change_formula")
                change_field = data.get("change_field")

                # Si no hay valor, saltar
                if change_formula is None or change_field is None:
                    continue

                upsert_change_order(
                    session=session,
                    job=job,
                    podio_item_id=podio_item_id,
                    podio_field=change_field,
                    change_formula=change_formula,
                    order=None,  # 🔥 IMPORTANTE → Project level
                    dry_run=dry_run
                )

            # -----------------------------
            # 4️⃣ UPSERT TECH CHANGE ORDERS
            # -----------------------------
            for tech_index, changes in order_change_data.items():

                order_obj = orders_map.get(tech_index)

                if not order_obj:
                    continue  # la order no fue creada o no existe

                for external_id, value in changes.items():

                    if value is None:
                        continue

                    upsert_change_order(
                        session=session,
                        job=job,
                        podio_item_id=podio_item_id,
                        podio_field=external_id,
                        change_formula=value,
                        order=order_obj,  # 🔥 IMPORTANTE → Order level
                        dry_run=dry_run
                    )

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }
