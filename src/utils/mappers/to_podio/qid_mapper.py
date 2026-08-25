from datetime import date, datetime
from ..convert_value_podio import convert_value_for_podio
from sqlmodel import select
from .job_fields_map import BASE_QID_FIELDS
from .limpieza_slots import asignar, normalizar
from src.models.ClientModel import Client
from src.models.BldgDeptModel import BuildingDept


def _importes_por_hueco(job_obj, config, valor_columna, session) -> dict:
    """`{external_id: importe}` de un campo `multi`.

    Cada alquiler, BD fee y compra escribe en el hueco que **declara** ocupar
    (`podio_field`), no en la posición que le toque por orden de creación. Los
    que aún no lo declaran —mientras el backfill no haya corrido— caen al
    reparto posicional de siempre, así que este cambio es inerte hasta que haya
    huecos asignados. Ver `src/utils/podio_slots.py`.
    """
    clave = config.get("familia")

    if clave and session and getattr(job_obj, "ID_Jobs", None):
        from src.utils import podio_slots

        fam = podio_slots.familia(clave)
        por_slot = podio_slots.payload_por_slot(session, fam, job_obj.ID_Jobs)
        por_slot.update(
            podio_slots.slots_legacy_posicionales(session, fam, job_obj.ID_Jobs))
        return por_slot

    # Sin sesión no hay registros que consultar: se usa la columna del job, que
    # es lo que alimenta el mapeo en las pruebas unitarias y en los dry-run.
    valores = valor_columna or []
    return {ext: valores[i] for i, ext in enumerate(config["external_ids"])
            if i < len(valores) and valores[i] is not None}


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

        # 🔹 MULTI FIELD — cada registro escribe en el hueco que DECLARA ocupar
        if config.get("multi"):
            por_slot = _importes_por_hueco(job_obj, config, value, session)

            for ext_id in config["external_ids"]:
                converted = convert_value_for_podio(
                    por_slot.get(ext_id), config["type"])

                # Un hueco que la base no puede rellenar NO se manda: escribir
                # `[]` aquí borraba el importe que el cliente tiene en Podio.
                asignar(payload, ext_id, converted, limpiar)

        # 🔹 NORMAL FIELD
        else:
            if value is None:
                continue

            end_value = None if config.get("no_end") else (
                getattr(job_obj, config["end_attr"], None) if config.get(
                    "end_attr") else None
            )
            converted = convert_value_for_podio(
                value, config["type"], end_value=end_value, with_time=config.get("with_time", False))

            if converted is not None:
                payload[config["external_id"]] = converted

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
