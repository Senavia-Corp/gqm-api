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
    PROJECT_CHANGE_ORDER_FIELDS,
    ORDER_CHANGE_ORDERS_FIELDS,
)
from src.utils.mappers.from_podio import payment_slots
from src.utils.mappers.from_podio.payment_slots import collect_payment_slots
from src.utils.middleware.logs.logs import logger



def _texto_del_item(item, ext_id):
    """Lee un campo `text` del item crudo. Devuelve None si falta o esta vacio."""
    if not ext_id:
        return None
    for f in item.get("fields", []) or []:
        if (f.get("external_id") or "").lower() != ext_id.lower():
            continue
        crudo = f.get("values") or []
        if not crudo:
            return None
        v = crudo[0].get("value", crudo[0]) if isinstance(crudo[0], dict) else crudo[0]
        return str(v) if v is not None else None
    return None

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

        # Carrera real: Podio reintenta y puede tener VARIOS hooks activos
        # sobre la misma app, así que el mismo item.create llega dos veces a
        # la vez. Sin savepoint, el INSERT perdedor explota en un autoflush
        # posterior (UniqueViolation en jobs_pkey) y devuelve 500 → Podio
        # reintenta otra vez y ensucia la dead-letter. Con savepoint, el
        # perdedor degrada a UPDATE del ganador: convergen al mismo estado.
        from sqlalchemy.exc import IntegrityError

        try:
            with session.begin_nested():
                session.add(new_job)
                session.flush()
            return new_job
        except IntegrityError:
            print(f"⚠️ {mapped['ID_Jobs']} ya insertado por otra entrega "
                  "concurrente — se degrada a UPDATE (idempotencia)")

        winner = session.exec(
            select(Job).where(
                or_(
                    Job.podio_item_id == podio_item_id,
                    Job.ID_Jobs == tracking_id,
                )
            )
        ).first()
        if not winner:
            raise
        for k, v in mapped.items():
            if getattr(winner, k) != v:
                setattr(winner, k, v)
        session.add(winner)
        return winner


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
    app_type: str,
    year: int | None = None,
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
    payments_by_tech = collect_payment_slots(fields, app_type, year)
    has_payment_model = payment_slots.habilitado(app_type)

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
            payments=payments_by_tech.get(tech_index, {}) if has_payment_model else None,
            job_type=app_type, year=year,
            check_numbers=_texto_del_item(item, payment_slots.campo_check_numbers(
                app_type, year, tech_index))
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


def _valor_money_del_item(item, ext_id):
    """Lee un campo `money` del ítem crudo de Podio.

    Devuelve `(presente, valor)`:
      - `(False, None)` → el campo **no viene** en el payload
      - `(True,  None)` → viene y está **vacío**
      - `(True,  float)` → viene con importe

    Leer del ítem y no de una columna del job es lo que permite distinguir
    «ausente» de «vacío», y lo que evita el desplazamiento: el lector `multi`
    (`podio_job_extractor.py`) sólo acumula los campos presentes, así que con
    `bldg-fees-2` vacío el importe del hueco 3 acababa en la fila del 2.
    """
    for f in item.get("fields", []) or []:
        f_ext = (f.get("external_id") or "").lower()
        if f_ext != ext_id.lower():
            continue
        crudo = f.get("values") or f.get("value")
        if not isinstance(crudo, list) or not crudo:
            return True, None
        v = crudo[0].get("value", crudo[0]) if isinstance(crudo[0], dict) else crudo[0]
        if isinstance(v, dict) and "value" in v:
            v = v["value"]
        try:
            return True, float(v)
        except (TypeError, ValueError):
            return True, None
    return False, None


def sync_familia_desde_podio(session, job, item, fam) -> None:
    """Aplica los importes de Podio sobre el registro que DECLARA cada hueco.

    Podio manda en los **importes**; la base manda en la **correspondencia**
    registro ↔ hueco. Reglas, en este orden:

    - campo ausente del payload      → no se toca nada
    - campo presente pero vacío      → **no se toca nada**. Decisión del cliente
      (Sebastian, 18-ago-2026): «si en Podio se elimina, no hace nada».
    - importe + registro que declara → se actualiza ese registro
    - importe + nadie lo declara     → se crea, sólo si la familia lo permite
      (BD fees sí; compras no, para no generar «ghost purchases»)

    Lo que ya NO hace, y era el daño: compactar la lista descartando los
    vacíos —que reasignaba importes entre registros distintos—, borrar los
    sobrantes con `session.delete`, y convertir un hueco vacío en un 0,00.
    """
    from src.utils import podio_slots
    from src.utils.id_generator import generate_custom_id

    if not job.ID_Jobs:
        return

    por_slot = podio_slots.ocupados(session, fam, job.ID_Jobs)
    # Para adoptar se usa la posicion SIN mirar el importe: un registro a cero
    # es justo el que tiene que recibir el valor de Podio. La regla del cero es
    # del sentido saliente.
    adopcion = podio_slots.posiciones_sin_declarar(session, fam, job.ID_Jobs)

    creador = next((p for p in fam.propietarios if p.crea_desde_podio), None)

    for indice, ext_id in enumerate(fam.external_ids):
        presente, val = _valor_money_del_item(item, ext_id)

        if not presente or val is None:
            continue                      # ausente o vacío: no se toca

        registro = por_slot.get(ext_id)

        # Mientras el backfill no haya corrido, el hueco lo ocupa de facto el
        # registro que le tocaba por posición. Se adopta y se declara.
        if registro is None and ext_id in adopcion:
            registro = adopcion.pop(ext_id)
            registro.podio_field = ext_id

        if registro is not None:
            for p in fam.propietarios:
                if isinstance(registro, p.modelo):
                    if float(getattr(registro, p.attr_importe, 0) or 0) != val:
                        setattr(registro, p.attr_importe, val)
                    # Builder_cost sólo se rellena si estaba vacío: conserva lo cotizado
                    if hasattr(registro, "Builder_cost") and not registro.Builder_cost:
                        registro.Builder_cost = val
                    break
            session.add(registro)
            continue

        if creador is None:
            logger.info(
                "Hueco %s de %s trae %.2f y ningún registro lo reclama; no se crea nada",
                ext_id, job.ID_Jobs, val)
            continue

        nuevo = creador.modelo(
            **{creador.modelo.__mapper__.primary_key[0].name:
               generate_custom_id(session, creador.modelo,
                                  creador.modelo.__mapper__.primary_key[0].name, "EST"),
               "ID_Jobs": job.ID_Jobs,
               "Cost_type": "BDF",
               "Status": "Approved",
               "Title": creador.titulo_nuevo.format(n=indice + 1),
               "Builder_cost": val,
               creador.attr_importe: val,
               "Quatity": 1,
               "podio_field": ext_id})
        session.add(nuevo)


def sync_bdf_from_podio(session, job, item):
    """BD Fees de Podio → EstimateCost(BDF, Approved), por hueco declarado."""
    from src.utils import podio_slots
    return sync_familia_desde_podio(
        session, job, item, podio_slots.familia("QID.bldg_dept_fees"))


def sync_purchases_from_podio(session, job, item):
    """PURCHASE 1..13 de Podio → alquileres aprobados y compras, por hueco
    declarado. El pool lo comparten las dos tablas (defecto G1)."""
    from src.utils import podio_slots
    return sync_familia_desde_podio(
        session, job, item, podio_slots.familia("QID.purchases_list"))

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
    add_job_orders_and_change_orders(session, job, item, app_type, year)
    # Las dos leen del `item` crudo, no de columnas del job: es lo único que
    # distingue «el campo no vino» de «lo vaciaron en Podio».
    sync_bdf_from_podio(session, job, item)
    sync_purchases_from_podio(session, job, item)
    sync_ptl_gc_fee_from_podio(session, job)
