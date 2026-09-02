import os
import re

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from src.utils.middleware.logs.logs import logger
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.podio.services.job_services import podio_jobs_router
from src.utils.id_generator import generate_custom_id
from src.models.JobModel import Job
from src.models.OrderModel import Order
from src.models.SubcontractorModel import Subcontractor
from src.models.ChangeOrderModel import ChangeOrder
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
    cos_declarados,
    cuotas_vaciables,
    slots_vaciables,
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
    notes: str,
    payments: dict | None = None,
    dry_run: bool = False
):
    # payments: {cuota(1..3): monto} — solo PAR. None = no tocar (QID/PTL);
    # dict (aunque vacío) = Podio es la fuente de verdad y se pisan los 3 slots.

    existing_order = session.exec(
        select(Order).where(
            Order.job_podio_id == podio_item_id,
            Order.tech_field == tech_field
        )
    ).first()

    if not existing_order and (formula is None or float(formula or 0) == 0):
        # ⛔ No creamos órdenes nuevas si no tienen fórmula (slots vacíos en Podio)
        return None, False

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

        if existing_order.Notes != notes:
            existing_order.Notes = notes
            changed = True

        if payments is not None:
            for slot in (1, 2, 3):
                attr = f"Payment_{slot}"
                new_value = payments.get(slot)
                if getattr(existing_order, attr) != new_value:
                    setattr(existing_order, attr, new_value)
                    changed = True

        if changed and not dry_run:
            session.add(existing_order)

        return existing_order, False  # False = no creado

    # 🔥 Generar ID
    prefix = "ORD"
    # OJO: `generate_custom_id` ya NO es un SELECT sin efectos. Desde que el
    # contador vive en `id_counters` (c5a8e3f24b17), pedir un ID hace un
    # UPDATE que COMMITEA en su propia conexion — fuera de la transaccion
    # del llamador, asi que ni el `if not dry_run` de abajo ni un rollback lo
    # deshacen. Pedirlo aqui hacia que una SIMULACION quemara numeros reales.
    # Un dry_run no puede tener efectos: ese es todo su contrato.
    new_id = f"{prefix}-DRYRUN" if dry_run else generate_custom_id(
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
        Notes=notes,
        ID_Subcontractor=subcontractor_id,
        Payment_1=(payments or {}).get(1),
        Payment_2=(payments or {}).get(2),
        Payment_3=(payments or {}).get(3),
    )

    if not dry_run:
        # SAVEPOINT + degradar a UPDATE.
        #
        # Esto era check-then-insert sin lock: entre el SELECT de arriba y este
        # INSERT cabe otra entrega del mismo evento (Podio reintenta, y una app
        # puede tener varios hooks), y las dos ven "no existe". Hasta ahora nada
        # lo paraba: la tabla no tenia restriccion.
        #
        # El dano esta VIVO y es exactamente uno: job_podio_id 3304340068
        # (PAR6095) con ORD68994 (110) y ORD69726 (330) en el mismo
        # `tech-1-ptl-original-pricing`. `recalculate_job_fields` recorre TODAS
        # las orders y las acumula, asi que suma 660 donde deberia sumar 550.
        #
        # Con `ux_order_job_slot` (migracion e7a3c9d21f80) el perdedor de la
        # carrera recibe IntegrityError; el savepoint evita que se lleve por
        # delante la transaccion entera y se degrada a UPDATE, que es lo que el
        # upsert queria hacer desde el principio.
        try:
            with session.begin_nested():
                session.add(new_order)
                session.flush()
        except IntegrityError as choque:
            if "ux_order_job_slot" not in str(getattr(choque, "orig", choque)):
                raise
            ganadora = session.exec(
                select(Order).where(
                    Order.job_podio_id == podio_item_id,
                    Order.tech_field == tech_field)
            ).first()
            if ganadora is None:
                raise
            logger.info(
                "otra entrega creo la Order de %s/%s; se actualiza en vez de "
                "duplicar", podio_item_id, tech_field)
            ganadora.Formula = formula
            ganadora.Adj_formula = adj_formula
            ganadora.ID_Subcontractor = subcontractor_id
            ganadora.Ptl_hd_materials = hd_materials
            ganadora.Notes = notes
            session.add(ganadora)
            return ganadora, False

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
    # OJO: `generate_custom_id` ya NO es un SELECT sin efectos. Desde que el
    # contador vive en `id_counters` (c5a8e3f24b17), pedir un ID hace un
    # UPDATE que COMMITEA en su propia conexion — fuera de la transaccion
    # del llamador, asi que ni el `if not dry_run` de abajo ni un rollback lo
    # deshacen. Pedirlo aqui hacia que una SIMULACION quemara numeros reales.
    # Un dry_run no puede tener efectos: ese es todo su contrato.
    new_id = f"{prefix}-DRYRUN" if dry_run else generate_custom_id(
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
        # Mismo patron que upsert_order: ver el comentario de alli.
        try:
            with session.begin_nested():
                session.add(new_co)
                session.flush()
        except IntegrityError as choque:
            if "ux_change_order_job_slot" not in str(getattr(choque, "orig", choque)):
                raise
            ganadora = session.exec(
                select(ChangeOrder).where(
                    ChangeOrder.job_podio_id == podio_item_id,
                    ChangeOrder.podio_field == podio_field)
            ).first()
            if ganadora is None:
                raise
            logger.info(
                "otra entrega creo el ChangeOrder de %s/%s; se actualiza en vez "
                "de duplicar", podio_item_id, podio_field)
            ganadora.ChangeOrderFormula = change_formula
            ganadora.ID_Order = order.ID_Order if order else None
            session.add(ganadora)
            return ganadora, False

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
# --- VACIADO DE SLOTS AUSENTES -
# ===============================
#
# Podio omite del item los campos vacios, y `item_de_confianza` relee SIEMPRE
# el item entero antes de escribir: un slot ausente significa "ese tecnico ya
# no esta en Podio". Los dos lectores construian `tech_data` solo con lo
# presente, asi que un slot que desaparecia ENTERO no se visitaba y la fila
# conservaba su dinero indefinidamente. Gemelo en filas del arreglo de columnas
# de `job_mapper.campos_vaciables`.
#
# Se VACIA, nunca se borra: `order` no tiene columna de soft-delete y borrar
# exigiria replicar aqui el desenlazado de `DELETE /order/<id>`. Vaciar
# converge igual (Formula=None -> baja `Adj_formula` -> bajan los agregados) y
# se deshace rellenando el campo en Podio.

# Lo que gobierna Podio en una Order. `Adj_formula` NO esta: la reescribe
# siempre `recalculate_order_formulas`, asi que vaciarla seria churn puro.
# `ID_Subcontractor` tampoco: desvincular saca la orden del portal de ese
# subcontratista (REG-110, `routes/Order.py:42`) y los agregados no lo leen.
COLUMNAS_DE_PODIO = ("Formula", "Ptl_hd_materials", "Notes")
COLUMNAS_DE_CUOTAS = ("Payment_1", "Payment_2", "Payment_3")


def vaciado_de_slots_activo() -> bool:
    """Interruptor de despliegue. Apagado, el comportamiento es el de siempre.

    Existe para que "desplegar" y "mover los agregados de 9.297 ordenes" no
    sean el mismo acto: se despliega apagado, se mide con
    `/admin/podio/obsoletos_ordenes`, y se enciende a mano.
    """
    return os.getenv("PODIO_VACIA_SLOTS", "").strip().lower() in (
        "1", "true", "yes", "on")


def _la_toco_un_humano(order) -> bool:
    """Algo que no puso el sync cuelga de esta Order.

    `upsert_order` nunca escribe `Title` ni vincula costes, facturas u
    oportunidades. Si algo de eso esta ahi, la fila la construyo una persona
    —tipicamente un PO desde el panel— y su slot puede no existir en Podio:
    `POST /order/?sync_podio=false` guarda sin avisar a Podio, y la ventana
    entre el commit y el `update_item` de `Order.py:370-376` deja el mismo
    rastro. Vaciarla destruiria un dato bueno.

    Mismo precedente que `sync_bdf_from_podio`: cuando el desajuste puede
    venir de nuestro propio lado, no se poda — se avisa.
    """
    return bool(order.Title or order.estimate_costs or order.financial_docs
                or order.opportunities)


def _avisar_saltada(order, motivo: dict) -> None:
    # Import tardio: `jobs_hook_sync` importa de este modulo, y al ejecutarse
    # esta funcion los dos ya estan cargados.
    from src.podio.webhook.jobs_hook_sync import record_failed_sync_propia

    record_failed_sync_propia(
        item_id=order.job_podio_id,
        hook_type="slot_vaciado_en_podio_con_datos_locales",
        payload=motivo,
        error="la Order tiene datos que no puso el sync; no se vacia")


def slots_y_cos_presentes(fields, job_type: str):
    """Lo que el item SI menciona: (indices de tecnico, external_ids de CO).

    Se mira el PAYLOAD, no `tech_data`. La diferencia importa: un
    `technician-N` presente cuyo Subcontractor no esta en la BD no llega a
    `tech_data` (`extract_subcontractor_from_field` devuelve None), y tomar eso
    por "el slot ya no esta" vaciaria una Order que Podio sigue teniendo.

    Se cuentan TODOS los mapas del slot —formula, adj, HD, notas, cuotas y el
    propio technician— porque cualquiera de ellos prueba que el tecnico sigue
    ahi. Predicado unico: lo usan los dos lectores y la ruta de medida.
    """
    presentes = {f.get("external_id") for f in fields
                 if f.get("external_id") and f.get("values")}

    mapas = (TECH_FORMULA_FIELDS.get(job_type, {}),
             TECH_ADJ_FORMULA_FIELDS.get(job_type, {}),
             TECH_HD_MATERIALS_FIELDS.get(job_type, {}),
             TECH_NOTES_FIELDS.get(job_type, {}),
             TECH_PAYMENT_FIELDS.get(job_type, {}),
             TECHNICIAN_FIELDS)
    vistos = {indice
              for mapa in mapas
              for indice, slugs in mapa.items()
              if presentes.intersection(slugs)}

    return vistos, presentes & cos_declarados(job_type)


def catalogo_de_slots(session, podio_item_ids) -> dict:
    """Indice en memoria de las filas por slot, para medir muchos items.

    Sin esto, `/admin/podio/obsoletos_ordenes` haria una consulta por slot y por
    item —hasta 80 por job— y el presupuesto de la funcion se agotaria antes de
    cubrir una app entera: la medida saldria siempre parcial. Con el indice, las
    9.297 orders y los 1.283 change orders de produccion caben de sobra en dos
    consultas.
    """
    refs = {str(r) for r in podio_item_ids if r}
    if not refs:
        return {"orders": {}, "change_orders": {}}

    ordenes = session.exec(select(Order).where(
        Order.job_podio_id.in_(refs), Order.tech_field.is_not(None))).all()
    cos = session.exec(select(ChangeOrder).where(
        ChangeOrder.job_podio_id.in_(refs),
        ChangeOrder.podio_field.is_not(None),
        ChangeOrder.ID_Order.is_not(None))).all()

    return {
        "orders": {(o.job_podio_id, o.tech_field): o for o in ordenes},
        "change_orders": {(c.job_podio_id, c.podio_field): c for c in cos},
    }


def _buscar_order(session, catalogo, podio_item_id, slugs):
    if catalogo is None:
        return session.exec(
            select(Order).where(Order.job_podio_id == podio_item_id,
                                Order.tech_field.in_(slugs))).first()
    for slug in slugs:
        fila = catalogo["orders"].get((podio_item_id, slug))
        if fila is not None:
            return fila
    return None


def _buscar_co(session, catalogo, podio_item_id, slug):
    if catalogo is None:
        return session.exec(
            select(ChangeOrder).where(
                ChangeOrder.job_podio_id == podio_item_id,
                ChangeOrder.podio_field == slug,
                ChangeOrder.ID_Order.is_not(None))).first()
    return catalogo["change_orders"].get((podio_item_id, slug))


def vaciar_slots_ausentes(session, podio_item_id: str, job_type: str, anio,
                          vistos, *, dry_run: bool = False,
                          catalogo: dict = None) -> list:
    """Vacia las Orders cuyo slot ya no viene en el item de Podio.

    `vistos` son los indices que el payload SI menciona, y salen de
    `slots_y_cos_presentes` — NO de las claves de `tech_data`: un `technician-N`
    cuyo Subcontractor no esta en la BD no llega a `tech_data`, y tomarlo por
    ausente vaciaria una Order que Podio sigue teniendo.

    Devuelve el informe de lo hecho —o de lo que se haria con `dry_run`— para
    que la ruta de medida use exactamente este predicado.
    """
    if not dry_run and not vaciado_de_slots_activo():
        return []  # `dry_run` no escribe, asi que la medida no pasa por el flag

    formula_map = TECH_FORMULA_FIELDS.get(job_type, {})
    con_cuotas = cuotas_vaciables(job_type, anio)
    informe = []

    for slot in sorted(slots_vaciables(job_type, anio) - set(vistos)):
        slugs = formula_map.get(slot) or []
        if not slugs:
            continue

        order = _buscar_order(session, catalogo, podio_item_id, slugs)
        if order is None:
            continue  # el slot nunca tuvo fila: nada que vaciar

        columnas = list(COLUMNAS_DE_PODIO)
        if slot in con_cuotas:
            columnas += list(COLUMNAS_DE_CUOTAS)

        antes = {c: getattr(order, c) for c in columnas
                 if getattr(order, c) is not None}
        if not antes:
            continue  # ya convergen; no se toca para no mover `updated_at`

        # `Adj_formula` no se vacia (la reescribe el recalculo local), pero se
        # informa: es lo que la fila aporta hoy a los agregados del job, o sea
        # la cota superior de lo que este vaciado mueve.
        fila = {"ID_Order": order.ID_Order, "slot": slot, "antes": antes,
                "adj_formula": order.Adj_formula, "saltada": False}

        if _la_toco_un_humano(order):
            fila["saltada"] = True
            logger.warning(
                "slot %s de %s vacio en Podio, pero %s tiene datos locales "
                "(Title/costes/facturas/oportunidades): NO se vacia %s",
                slot, podio_item_id, order.ID_Order, sorted(antes))
            if not dry_run:
                _avisar_saltada(order, {"ID_Order": order.ID_Order,
                                        "job_podio_id": podio_item_id,
                                        "slot": slot,
                                        "columnas": sorted(antes)})
            informe.append(fila)
            continue

        if not dry_run:
            for columna in antes:
                setattr(order, columna, None)
            session.add(order)
        # El verbo distingue la simulacion: la ruta de medida recorre miles de
        # items en `dry_run`, y un log que dijera "se vacia" en los dos casos
        # dejaria miles de lineas afirmando que el cambio corrio cuando no.
        logger.info("Order %s: el slot %s ya no esta en Podio, %s %s",
                    order.ID_Order, slot,
                    "SE VACIARIA" if dry_run else "se vacia", antes)
        informe.append(fila)

    return informe


def vaciar_cos_ausentes(session, podio_item_id: str, job_type: str, presentes,
                        *, dry_run: bool = False,
                        catalogo: dict = None) -> list:
    """Vacia los Change Orders de NIVEL ORDEN que ya no vienen en el item.

    `presentes` son los external_ids de CO que el payload si trae. Solo se
    tocan los que tienen `ID_Order`: los de nivel proyecto mueven
    `Acc_receivable` y van en otra fase. Nunca se toca `ID_Order` —reparentar
    un CO lo colaria en `Gqm_total_change_orders`— ni se borra ninguna fila.
    """
    if not dry_run and not vaciado_de_slots_activo():
        return []  # ver `vaciar_slots_ausentes`

    informe = []
    for slug in sorted(cos_declarados(job_type) - set(presentes)):
        co = _buscar_co(session, catalogo, podio_item_id, slug)
        if co is None or co.ChangeOrderFormula is None:
            continue

        antes = {"ChangeOrderFormula": co.ChangeOrderFormula}
        if not dry_run:
            co.ChangeOrderFormula = None
            session.add(co)
        logger.info("ChangeOrder %s: el campo %s ya no esta en Podio, %s %s",
                    co.ID_ChangeOrder, slug,
                    "SE VACIARIA" if dry_run else "se vacia", antes)
        informe.append({"ID_ChangeOrder": co.ID_ChangeOrder, "slot": slug,
                        "antes": antes, "saltada": False})

    return informe


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
                matched = False
                for tech_index, field_ids in TECHNICIAN_FIELDS.items():
                    if external_id in field_ids:
                        subcontractor = extract_subcontractor_from_field(
                            session, f)

                        if subcontractor:
                            tech_data.setdefault(tech_index, {})
                            tech_data[tech_index]["subcontractor_id"] = subcontractor.ID_Subcontractor
                            tech_data[tech_index]["tech_field"] = external_id

                        matched = True
                        break

                if matched:
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

            # Cuotas de PAR (REG-001)
            payments_by_tech = collect_payment_slots(fields, job_type)
            has_payment_model = job_type in TECH_PAYMENT_FIELDS

            orders_map = {}

            for tech_index, data in tech_data.items():

                formula = data.get("formula")
                adj_formula = data.get("adj_formula")
                subcontractor_id = data.get("subcontractor_id")
                tech_field = data.get("formula_field")
                if not tech_field:
                    possible_fields = formula_map.get(tech_index, [])
                    tech_field = possible_fields[0] if possible_fields else None

                hd_materials = data.get("hd_materials")
                notes = data.get("notes")

                if tech_field is None:
                    continue

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
                    notes=notes,
                    payments=payments_by_tech.get(tech_index, {}) if has_payment_model else None,
                    dry_run=dry_run
                )

                orders_map[tech_index] = order

            # Los slots que YA NO vienen en el item (mismo arreglo que en el
            # webhook). Aqui importa mas: esta corrida no llama a
            # `recalculate_and_apply`, asi que lo que quede mal se persiste.
            slots_vistos, cos_vistos = slots_y_cos_presentes(fields, job_type)
            vaciar_slots_ausentes(session, podio_item_id, job_type, year,
                                  slots_vistos, dry_run=dry_run)

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

            vaciar_cos_ausentes(session, podio_item_id, job_type, cos_vistos,
                                dry_run=dry_run)

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }
