from sqlmodel import select
from src.utils.mappers.mapper_aux_functions import has_html, clean_html
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from src.models.JobModel import Job
from src.utils.mappers.podio_relationships import get_related_app_ids, get_contact_profile_ids
from src.utils.mappers.from_podio.jobs_relationships import JOB_MEMBER_FIELDS, upsert_job_member_link
from src.models.MemberModel import Member
from src.models.SubcontractorModel import Subcontractor
from src.models.link_models.JobSubcontractor import JobSubcontractorLink
from src.models.ClientModel import Client
from src.models.BldgDeptModel import BuildingDept
from ..sync.sync_orders import upsert_order, upsert_change_order, extract_subcontractor_from_field
from src.utils.mappers.from_podio.order_changeorder_mapper import (
    TECHNICIAN_FIELDS,
    TECH_FORMULA_FIELDS,
    TECH_ADJ_FORMULA_FIELDS,
    TECH_HD_MATERIALS_FIELDS,
    TECH_NOTES_FIELDS,
    TECH_PAYMENT_FIELDS,
    PROJECT_CHANGE_ORDER_FIELDS,
    ORDER_CHANGE_ORDERS_FIELDS,
    collect_payment_slots,
)
from src.utils.middleware.logs.logs import logger


def upsert_job_from_item(session, item, app_type, year=None):

    mapped = map_podio_item_to_job(item)
    if year:
        # La ruta del webhook conoce la app-año: persistirla (REG-015)
        mapped["podio_app_year"] = year

    podio_item_id = mapped.get("podio_item_id")
    tracking_id = mapped.get("ID_Jobs")

    # -------------------------
    # Validaciones mínimas
    # -------------------------
    if not podio_item_id or not tracking_id:
        print(f"⚠️ Job inválido (podio_item_id={podio_item_id})")
        return None

    # pyrefly: ignore [missing-import]......
    from sqlalchemy import or_
    
    existing = session.exec(
        select(Job).where(
            or_(
                Job.podio_item_id == podio_item_id,
                Job.ID_Jobs == tracking_id
            )
        )
    ).first()

    # =========================
    # UPDATE
    # =========================
    if existing:

        changes = {
            k: v for k, v in mapped.items()
            if getattr(existing, k) != v
        }

        if changes:
            print(
                f"🟡 Update {existing.ID_Jobs} → {list(changes.keys())}"
            )

            for k, v in changes.items():
                setattr(existing, k, v)

            session.add(existing)

        else:
            print(f"⚪ {existing.ID_Jobs} — sin cambios")

        return existing

    # =========================
    # INSERT
    # =========================
    else:

        print(f"🟢 Insert {mapped['ID_Jobs']}")

        new_job = Job(**mapped)
        session.add(new_job)

        return new_job


def add_job_relations(session, job, item):
    """
    Sincroniza todas las relaciones M:1 del Job
    (modo webhook, un solo item).
    """

    RELATION_CONFIG = {
        "client": {
            "model": Client,
            "fk_field": "ID_Client",
            "external_id": "relationship",
            "internal_id": "ID_Client"
        },
        "building_dept": {
            "model": BuildingDept,
            "fk_field": "ID_BldgDept",
            "external_id": "bldg-dept",
            "internal_id": "ID_BldgDept"
        },
    }

    fields = item.get("fields", [])

    for config in RELATION_CONFIG.values():

        related_ids = get_related_app_ids(
            fields=fields,
            external_id=config["external_id"],
            session=session,
            model=config["model"],
            podio_field="podio_item_id",
            internal_id_field=config["internal_id"]
        )

        # Protección contra múltiples relaciones
        if len(related_ids) > 1:
            print(
                f"⚠️ Job {job.ID_Jobs} tiene múltiples "
                f"{config['model'].__name__} en Podio"
            )

        new_value = related_ids[0] if related_ids else None
        current_value = getattr(job, config["fk_field"])

        if current_value != new_value:
            print(f"🟡 Update {job.ID_Jobs} → {config['fk_field']}")
            setattr(job, config["fk_field"], new_value)
            session.add(job)
        else:
            print(
                f"⚪ {job.ID_Jobs} — sin cambios en {config['model'].__name__}")


def add_job_related_members(session, job, item, app_type, year):
    """
    Aplica relaciones M:N Job ↔ Member
    en modo webhook (un solo item).
    """

    config = JOB_MEMBER_FIELDS.get((app_type, year))

    if not config:
        logger.warning(
            "No hay configuración de miembros para app_type=%s year=%s", app_type, year)
        return

    fields = item.get("fields", [])

    for external_id, cfg in config.items():

        rol = cfg["rol"]
        field_type = cfg["type"]

        # -----------------------------------
        # CONTACT FIELD
        # -----------------------------------
        if field_type == "contact":

            profile_ids = get_contact_profile_ids(
                fields=fields,
                external_id=external_id
            )

            for profile_id in profile_ids:

                member = session.exec(
                    select(Member).where(
                        Member.podio_profile_id == profile_id
                    )
                ).first()

                if not member:
                    continue

                created, updated = upsert_job_member_link(
                    session=session,
                    job_id=job.ID_Jobs,
                    member_id=member.ID_Member,
                    rol=rol
                )

        # -----------------------------------
        # APP FIELD
        # -----------------------------------
        elif field_type == "app":

            related_ids = get_related_app_ids(
                fields=fields,
                external_id=external_id,
                session=session,
                model=Member,
                podio_field="podio_item_id",
                internal_id_field="ID_Member"
            )

            for member_id in related_ids:

                upsert_job_member_link(
                    session=session,
                    job_id=job.ID_Jobs,
                    member_id=member_id,
                    rol=rol
                )


def add_job_related_subcontractor(session, job, item):
    """
    Aplica relaciones M:N Job ↔ Subcontractor
    en modo webhook (un solo item).
    """

    fields = item.get("fields", [])

    for f in fields:

        external_id = f.get("external_id")

        # Detecta technician-*
        if not external_id or not external_id.startswith("technician"):
            continue

        values = f.get("values", [])
        if not values:
            continue

        for v in values:

            podio_related_id = v.get("value", {}).get("item_id")
            if not podio_related_id:
                continue

            subcontractor = session.exec(
                select(Subcontractor).where(
                    Subcontractor.podio_item_id == str(podio_related_id)
                )
            ).first()

            if not subcontractor:
                print(
                    f"⚠️ Subcontractor {podio_related_id} no existe en DB"
                )
                continue

            link = session.get(
                JobSubcontractorLink,
                (job.ID_Jobs, subcontractor.ID_Subcontractor)
            )

            if link:
                continue

            from sqlalchemy.exc import IntegrityError
            try:
                with session.begin_nested():
                    session.add(
                        JobSubcontractorLink(
                            job_id=job.ID_Jobs,
                            subcontr_id=subcontractor.ID_Subcontractor,
                            position=external_id
                        )
                    )
                    session.flush()
                print(
                    f"🟢 Link Job {job.ID_Jobs} ↔ Subc "
                    f"{subcontractor.ID_Subcontractor}"
                )
            except IntegrityError:
                # Ya existe o hubo violación de unicidad por concurrencia, lo ignoramos
                pass


def add_job_orders_and_change_orders(
    session,
    job,
    item: dict,
    app_type: str
):
    """
    Procesa Orders y Change Orders desde un solo item (webhook).
    """

    fields = item.get("fields", [])
    podio_item_id = str(item.get("item_id"))

    tech_data = {}
    order_change_data = {}

    formula_map = TECH_FORMULA_FIELDS.get(app_type, {})
    adj_map = TECH_ADJ_FORMULA_FIELDS.get(app_type, {})
    hd_map = TECH_HD_MATERIALS_FIELDS.get(app_type, {})
    notes_map = TECH_NOTES_FIELDS.get(app_type, {})
    project_changeor_map = PROJECT_CHANGE_ORDER_FIELDS.get(app_type, {})
    order_change_orders_map = ORDER_CHANGE_ORDERS_FIELDS.get(app_type, {})

    # =============================
    # 1️⃣ PARSEAR FIELDS
    # =============================

    for f in fields:

        external_id = f.get("external_id")
        values = f.get("values", [])

        if not external_id or not values:
            continue

        value = values[0].get("value")

        # -------- TECH SUBCONTRACTOR --------
        for tech_index, field_ids in TECHNICIAN_FIELDS.items():
            if external_id in field_ids:
                subcontractor = extract_subcontractor_from_field(session, f)

                if subcontractor:
                    tech_data.setdefault(tech_index, {})
                    tech_data[tech_index]["subcontractor_id"] = subcontractor.ID_Subcontractor
                    tech_data[tech_index]["tech_field"] = external_id

                continue

        # -------- TECH FORMULA --------
        for tech_index, field_ids in formula_map.items():
            if external_id in field_ids:
                tech_data.setdefault(tech_index, {})
                tech_data[tech_index]["formula"] = value
                tech_data[tech_index]["formula_field"] = external_id
                break

        # -------- TECH ADJ --------
        for tech_index, field_ids in adj_map.items():
            if external_id in field_ids:
                tech_data.setdefault(tech_index, {})
                tech_data[tech_index]["adj_formula"] = value
                break

        # -------- TECH HD MATERIALS --------
        for tech_index, field_ids in hd_map.items():
            if external_id in field_ids:
                tech_data.setdefault(tech_index, {})
                tech_data[tech_index]["hd_materials"] = value
                tech_data[tech_index]["hd_materials_field"] = external_id
                break

        # -------- TECH NOTES --------
        for tech_index, field_ids in notes_map.items():
            if external_id in field_ids:
                clean_value = clean_html(value) if has_html(value) else value
                tech_data.setdefault(tech_index, {})
                tech_data[tech_index]["notes"] = clean_value
                tech_data[tech_index]["notes_field"] = external_id
                break

        # -------- PROJECT CHANGE ORDERS --------
        for tech_index, field_ids in project_changeor_map.items():
            if external_id in field_ids:
                tech_data.setdefault(tech_index, {})
                tech_data[tech_index]["change_formula"] = value
                tech_data[tech_index]["change_field"] = external_id
                break

        # -------- ORDER CHANGE ORDERS --------
        for tech_index, field_ids in order_change_orders_map.items():
            if external_id in field_ids:
                order_change_data.setdefault(tech_index, {})
                order_change_data[tech_index][external_id] = value
                break

    # =============================
    # 2️⃣ UPSERT ORDERS
    # =============================

    # Cuotas de PAR (REG-001): Podio es la fuente de verdad de los cheques
    payments_by_tech = collect_payment_slots(fields, app_type)
    has_payment_model = app_type in TECH_PAYMENT_FIELDS

    orders_map = {}

    for tech_index, data in tech_data.items():

        formula_field = data.get("formula_field")
        if not formula_field:
            possible_fields = formula_map.get(tech_index, [])
            formula_field = possible_fields[0] if possible_fields else None

        order, _ = upsert_order(
            session=session,
            job=job,
            podio_item_id=podio_item_id,
            subcontractor_id=data.get("subcontractor_id"),
            tech_index=tech_index,
            formula=data.get("formula"),
            adj_formula=data.get("adj_formula"),
            tech_field=formula_field,
            hd_materials=data.get("hd_materials"),
            notes=data.get("notes"),
            payments=payments_by_tech.get(tech_index, {}) if has_payment_model else None
        )

        orders_map[tech_index] = order

    # =============================
    # 3️⃣ PROJECT CHANGE ORDERS
    # =============================

    for tech_index, data in tech_data.items():

        change_formula = data.get("change_formula")
        change_field = data.get("change_field")

        if change_formula is None or change_field is None:
            continue

        upsert_change_order(
            session=session,
            job=job,
            podio_item_id=podio_item_id,
            podio_field=change_field,
            change_formula=change_formula,
            order=None
        )

    # =============================
    # 4️⃣ ORDER CHANGE ORDERS
    # =============================

    for tech_index, changes in order_change_data.items():

        order_obj = orders_map.get(tech_index)
        if not order_obj:
            from src.models.OrderModel import Order
            possible_fields = formula_map.get(tech_index, [])
            if possible_fields:
                order_obj = session.exec(
                    select(Order).where(
                        Order.job_podio_id == podio_item_id,
                        Order.tech_field.in_(possible_fields)
                    )
                ).first()

        if not order_obj:
            continue

        for external_id, value in changes.items():

            if value is None:
                continue

            upsert_change_order(
                session=session,
                job=job,
                podio_item_id=podio_item_id,
                podio_field=external_id,
                change_formula=value,
                order=order_obj
            )


def sync_bdf_from_podio(session, job):
    """
    Sincroniza los valores de Bldg_dept_fees traídos desde Podio
    (Job.Bldg_dept_fees) con los registros EstimateCost(BDF) para que
    el UI del panel refleje los cambios hechos en Podio y no sean sobreescritos.
    """
    if job.Bldg_dept_fees is None:
        return

    from src.models.EstimateCostModel import EstimateCost
    from src.utils.id_generator import generate_custom_id

    # Obtener los EstimateCost BDF Aprobados existentes
    bdf_costs = session.exec(
        select(EstimateCost).where(
            EstimateCost.ID_Jobs == job.ID_Jobs,
            EstimateCost.Cost_type == "BDF",
            EstimateCost.Status == "Approved"
        ).order_by(EstimateCost.ID_EstimateCost)
    ).all()

    # Los valores que vienen de Podio (aseguramos floats validos)
    try:
        podio_bdfs = [float(v) for v in job.Bldg_dept_fees if v is not None]
    except Exception:
        podio_bdfs = []

    # Actualizar o crear
    for i, val in enumerate(podio_bdfs):
        if i < len(bdf_costs):
            # Actualizar existente
            cost = bdf_costs[i]
            if float(cost.Client_price or 0) != val:
                cost.Client_price = val
                # Si el Builder_cost está vacío, lo llenamos, si no lo dejamos para conservar lo cotizado
                if not cost.Builder_cost:
                    cost.Builder_cost = val
                session.add(cost)
        else:
            # Crear nuevo costo desde Podio
            new_cost = EstimateCost(
                ID_EstimateCost=generate_custom_id(session, EstimateCost, "ID_EstimateCost", "EST"),
                ID_Jobs=job.ID_Jobs,
                Cost_type="BDF",
                Status="Approved",
                Title=f"Bldg Dept Fee {i+1} (Podio)",
                Builder_cost=val,
                Client_price=val,
                Quatity=1
            )
            session.add(new_cost)

    # Eliminar los excedentes si en Podio borraron uno
    if len(bdf_costs) > len(podio_bdfs):
        for cost in bdf_costs[len(podio_bdfs):]:
            session.delete(cost)


def sync_purchases_from_podio(session, job, item):
    """
    Sincroniza los valores de PURCHASE 1..13 traídos desde Podio
    con los registros de Rent (EstimateCost) y Purchase para que
    el UI del panel refleje los cambios hechos en Podio.
    """
    from src.models.EstimateCostModel import EstimateCost
    from src.models.PurchaseModel import Purchase
    from src.utils.id_generator import generate_custom_id

    # IDs externos configurados en Podio para los materiales
    PURCHASES_EXT_IDS = [
        "materials-purchased-1-2",
        "materials-purchased-2",
        "materials-purchased-3",
        "material-purchase-4",
        "material-purchase-5",
        "material-purchase-6",
        "material-purchase-7",
        "material-purchase-8",
        "material-purchase-9",
        "material-purchase-10",
        "material-purchase-11",
        "material-purchase-12",
        "material-purchase-13"
    ]

    podio_purchases = []
    fields = item.get("fields", [])
    
    for ext_id in PURCHASES_EXT_IDS:
        val = None
        for f in fields:
            f_ext = f.get("external_id")
            if f_ext and f_ext.lower() == ext_id:
                raw = f.get("values") or f.get("value")
                if isinstance(raw, list) and raw:
                    raw_val = raw[0].get("value", raw[0])
                    if isinstance(raw_val, dict) and "value" in raw_val:
                        try:
                            val = float(raw_val["value"])
                        except Exception:
                            pass
                    else:
                        try:
                            val = float(raw_val)
                        except Exception:
                            pass
                break
        podio_purchases.append(val)

    # Eliminar los 'None' del final para saber cuántos items reales hay
    while podio_purchases and podio_purchases[-1] is None:
        podio_purchases.pop()

    # Obtener Rents y Purchases locales
    rents = session.exec(
        select(EstimateCost).where(
            EstimateCost.ID_Jobs == job.ID_Jobs,
            EstimateCost.Cost_type == "Rent",
            EstimateCost.Status == "Approved"
        ).order_by(EstimateCost.ID_EstimateCost)
    ).all()

    purchases = session.exec(
        select(Purchase).where(Purchase.ID_Jobs == job.ID_Jobs).order_by(Purchase.ID_Purchase)
    ).all()

    # Recorrer los valores de Podio
    for i, val in enumerate(podio_purchases):
        if val is None:
            # En Podio pueden borrar un valor intermedio. Si es None, lo tomamos como 0
            val = 0.0

        if i < len(rents):
            # Es un Rent
            r = rents[i]
            if float(r.Client_price or 0) != val:
                r.Client_price = val
                session.add(r)
        elif i < len(rents) + len(purchases):
            # Es un Purchase
            p = purchases[i - len(rents)]
            if float(p.Total_spending or 0) != val:
                p.Total_spending = val
                session.add(p)
        # Nota: No creamos nuevos Purchases automáticamente desde Podio.
        # Esto previene que datos residuales en Podio (o Rentas que aún están en estado "Estimated")
        # generen "ghost purchases" cada vez que se dispara un webhook.


def sync_ptl_gc_fee_from_podio(session, job):
    """
    Sincroniza el valor de Ptl_gc_fee traído desde Podio
    con los registros EstimateCost(PTLGCF) para que el UI del panel
    refleje los cambios hechos en Podio y no sean sobreescritos.
    """
    if job.Ptl_gc_fee is None:
        return

    from src.models.EstimateCostModel import EstimateCost
    from src.utils.id_generator import generate_custom_id

    # Obtener los EstimateCost PTLGCF existentes
    gc_costs = session.exec(
        select(EstimateCost).where(
            EstimateCost.ID_Jobs == job.ID_Jobs,
            EstimateCost.Cost_type == "PTLGCF"
        ).order_by(EstimateCost.ID_EstimateCost)
    ).all()

    val = float(job.Ptl_gc_fee)

    if gc_costs:
        cost = gc_costs[0]
        if float(cost.Client_price or 0) != val or float(cost.Builder_cost or 0) != val:
            cost.Client_price = val
            cost.Builder_cost = val
            session.add(cost)
        
        # Eliminar excedentes si por alguna razón hay más de uno
        if len(gc_costs) > 1:
            for extra_cost in gc_costs[1:]:
                session.delete(extra_cost)
    else:
        # Solo creamos un costo nuevo si el valor es mayor a cero
        if val > 0:
            new_cost = EstimateCost(
                ID_EstimateCost=generate_custom_id(session, EstimateCost, "ID_EstimateCost", "EST"),
                ID_Jobs=job.ID_Jobs,
                Cost_type="PTLGCF",
                Status="Approved",
                Title="PTL GC Fee (Podio)",
                Builder_cost=val,
                Client_price=val,
                Quatity=1.0
            )
            session.add(new_cost)


# -------- FUNCIÓN PARA UNIFICAR JOB FASE 1 Y 2
def process_jobs_podio(session, item, app_type, year):
    job = upsert_job_from_item(session, item, app_type, year=year)

    if not job:
        return

    add_job_relations(session, job, item)
    add_job_related_members(session, job, item, app_type, year)
    add_job_related_subcontractor(session, job, item)
    add_job_orders_and_change_orders(session, job, item, app_type)
    sync_bdf_from_podio(session, job)
    sync_purchases_from_podio(session, job, item)
    sync_ptl_gc_fee_from_podio(session, job)
