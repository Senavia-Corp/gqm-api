from datetime import date, datetime
from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from .job_fields_map import BASE_QID_FIELDS
from .limpieza_slots import asignar, normalizar
from src.models.ClientModel import Client
from src.models.BldgDeptModel import BuildingDept


def map_job_to_podio_qid(job_obj, session=None, year=None, limpiar_slots=None):
    # Year-specific mapping for category fields
    if not year:
        from flask import request
        try:
            year = request.args.get("year", type=int)
        except Exception:
            pass
    if not year:
        for dt_attr in ["Date_assigned", "Date_Received", "Estimated_start_date"]:
            val = getattr(job_obj, dt_attr, None)
            if val:
                if isinstance(val, (date, datetime)):
                    year = val.year
                    break
                elif isinstance(val, str) and len(val) >= 4:
                    try:
                        year = int(val[:4])
                        break
                    except ValueError:
                        pass
    if not year:
        year = 2026

    payload = {}
    limpiar = normalizar(limpiar_slots)
    # Campos normales
    for attr, config in BASE_QID_FIELDS.items():
        value = getattr(job_obj, attr, None)

        # 🔹 DYNAMIC CALCULATION FOR Purchases_list
        if attr == "Purchases_list" and session:
            p_list = []
            if job_obj.ID_Jobs:
                from src.models.EstimateCostModel import EstimateCost
                from src.models.PurchaseModel import Purchase
                rents = session.exec(
                    select(EstimateCost).where(
                        EstimateCost.ID_Jobs == job_obj.ID_Jobs, 
                        EstimateCost.Cost_type == "Rent", 
                        EstimateCost.Status == "Approved"
                    ).order_by(EstimateCost.ID_EstimateCost)
                ).all()
                purchases = session.exec(
                    select(Purchase).where(Purchase.ID_Jobs == job_obj.ID_Jobs).order_by(Purchase.ID_Purchase)
                ).all()
                for r in rents:
                    p_list.append(float(r.Client_price if r.Client_price is not None else r.Builder_cost or 0))
                for p in purchases:
                    p_list.append(float(p.Total_spending or 0))
            value = (p_list + [None]*13)[:13]

        # 🔹 MULTI FIELD (Bldg_dept_fees)
        if config.get("multi"):
            values = value or []

            for i, ext_id in enumerate(config["external_ids"]):
                v = values[i] if i < len(values) else None

                converted = convert_value_for_podio(v, config["type"])

                # Un hueco que la base no puede rellenar NO se manda: escribir
                # `[]` aquí borraba el importe que el cliente tiene en Podio.
                asignar(payload, ext_id, converted, limpiar)

        # 🔹 NORMAL FIELD
        else:
            # Vacío = ausencia de dato: ni se convierte. Para los tipos lista,
            # convertir un vacío daría `[]`, que en Podio BORRA el campo. Sólo
            # `limpiar_slots` autoriza ese borrado.
            if value in (None, ""):
                converted = None
            else:
                end_value = None if config.get("no_end") else (
                    getattr(job_obj, config["end_attr"], None) if config.get(
                        "end_attr") else None
                )
                converted = convert_value_for_podio(
                    value, config["type"], end_value=end_value, with_time=config.get("with_time", False))

            asignar(payload, config["external_id"], converted, limpiar)

    # Relación con Client (M:1). Que la app no sepa el cliente no autoriza a
    # desvincularlo en Podio: sólo se vacía si se pide por `limpiar_slots`.
    client_internal_id = job_obj.ID_Client
    client_valor = None

    if client_internal_id and session:
        client = session.exec(
            select(Client).where(Client.ID_Client == client_internal_id)
        ).first()

        if client and client.podio_item_id:
            client_valor = convert_value_for_podio(client.podio_item_id, "app")

    asignar(payload, "relationship", client_valor, limpiar)

    # Relación con Building Department (M:1). Mismo criterio: 6.438 de los 6.497
    # QID de producción no tienen `ID_BldgDept`, y les estábamos borrando el
    # departamento que sí tienen en Podio.
    bldg_internal_id = job_obj.ID_BldgDept
    bldg_valor = None

    if bldg_internal_id and session:
        bldg_dept = session.exec(
            select(BuildingDept).where(
                BuildingDept.ID_BldgDept == bldg_internal_id)
        ).first()

        if bldg_dept and bldg_dept.podio_item_id:
            bldg_valor = convert_value_for_podio(bldg_dept.podio_item_id, "app")

    asignar(payload, "bldg-dept", bldg_valor, limpiar)

    # Relaciones con Members y Subcontractors (M:N) se mandan desde los links

    # Para debug
    print("🚀 Payload final para Podio:", payload)

    return payload
