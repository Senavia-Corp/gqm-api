from ...id_generator import generate_custom_id
from src.podio.services.order_services import TECH_FORMULA_FIELDS
from src.models.OrderModel import Order
from sqlmodel import select


def map_podio_item_to_order(item):
    """
    Devuelve una lista de dicts para cada TECH Formula con valor en un item de Podio.
    Cada dict contiene Formula, tech_field y job_podio_id.
    """
    fields = item.get("fields", [])
    app_type = item.get("app", {}).get("external_id", "QID")  # default QID

    orders = []

    for _, external_id in TECH_FORMULA_FIELDS[app_type].items():
        for f in fields:
            if f.get("external_id") == external_id:
                vals = f.get("values", [])
                if vals:
                    v = vals[0].get("value")
                    if v is not None:
                        try:
                            formula = float(v)
                        except (ValueError, TypeError):
                            formula = v
                        orders.append({
                            "Formula": formula,
                            "tech_field": external_id,
                            "job_podio_id": str(item.get("item_id")),
                        })
                break  # una vez encontrado el field, no buscamos más en fields

    return orders


def process_podio_order(item: dict, session, event_type: str):
    """
    Procesa un item de Podio y crea o actualiza Orders en DB
    de manera específica para los campos TECH Formula.
    """
    orders_data = map_podio_item_to_order(item)
    if not orders_data:
        print(
            f"⚠️ No hay valores de TECH Formula para item {item.get('item_id')}, se omite.")
        return

    for order_data in orders_data:
        item_id = order_data["job_podio_id"]
        tech_field = order_data["tech_field"]
        formula_value = order_data["Formula"]

        existing_order = session.exec(
            select(Order).where(
                (Order.job_podio_id == item_id) &
                (Order.tech_field == tech_field)
            )
        ).first()

        if existing_order:
            # Actualizar
            existing_order.Formula = formula_value
            session.commit()
            print(
                f"🔄 Order actualizado | tech_field={tech_field} | Formula={formula_value}")
        else:
            # Crear nuevo Order
            prefix = "ORD"
            new_id = generate_custom_id(session, Order, "ID_Order", prefix)
            order_data["ID_Order"] = new_id

            new_order = Order(**order_data)
            session.add(new_order)
            session.commit()
            print(
                f"✅ Order creado | tech_field={tech_field} | ID_Order={new_id}")
