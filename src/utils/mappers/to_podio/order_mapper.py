from ..convert_value_podio import convert_value_for_podio
from src.podio.services.order_services import get_next_available_tech_field


# Mapeo para hacer POST en el campo de TECH Formula según tipo de Job
def map_order_to_podio(order_obj, job_type, session):
    payload = {}

    # 1. Obtener campo TECH disponible
    tech_field = get_next_available_tech_field(
        session=session,
        job_podio_id=order_obj.job_podio_id,
        job_type=job_type
    )

    # 2. Guardar ese campo en el registro Order
    order_obj.tech_field = tech_field

    # 3. Pasar Formula a ese campo
    payload[tech_field] = convert_value_for_podio(
        tech_field,
        order_obj.Formula
    )

    print("🚀 Payload POST Order → Podio:", payload)
    return payload


# Mapeo para hacer PATCH con external-id
def map_order_patch_to_podio(order_obj):
    if not order_obj.tech_field:
        raise Exception("Order no tiene tech_field asignado.")

    return {
        order_obj.tech_field: convert_value_for_podio(
            order_obj.tech_field,
            order_obj.Formula
        )
    }


# Mapeo para hacer "DELETE" con external-id
def map_order_delete_to_podio(order_obj):
    if not order_obj.tech_field:
        raise Exception("Order no tiene tech_field asignado.")

    return {
        order_obj.tech_field: []
    }
