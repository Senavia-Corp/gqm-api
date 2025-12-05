from datetime import date, datetime
from decimal import Decimal

PODIO_FIELD_TYPES = {
    # Campos de QID
    "id-projects-workorder": "text",
    "client-2": "app",
    "project-location-2": "location",
    "job-status-2": "category",
    "project-name-2": "text",
    "powtnwo": "text",
    "service-type-3": "category",
    "date-assigned-2": "date",
    "gqm-adj-formula-pricing-2": "calculation",
    "gqm-target-sold-pricing": "text",
    "gqm-target-return": "text",
    "2023-gqm-final": "text",
    "2023-gqm-premium-in": "text",
    "gqm-final-sold-pricing": "text",
    "gqm-total-change-orders-2": "number",

    # Campos de PTL
    "titulo": "text",
    "client": "app",
    "location": "location",
    "mgmt-member": "app",
    "categoria": "category",
    "estimated-start-date": "date",

    "gqm-total-change-orders": "number",
    "gqm-adj-formula-total-cost": "number",
    "ptl-pricing-target": "category",
    "gqm-target-ptl-2": "calculation",
    "gqm-inc-collected-premium": "number",
    "2025-gqm-final-sold-ptl": "number",

    # Campos de PAR
    "titulo": "text",
    "client": "app",
    "job-status": "category",
    "week-assigned": "date",
    "gqm-formula-pricing-2": "calculation",
    "gqm-target-sold-par": "money",
    "gqm-target-par-return-2": "calculation",
    "gqm-premium-in-par-2": "calculation",

    # Campos de Clients
    "titulo": "text",
    "parent-mgmt-company": "contact",
    "parent-company": "text",
    "address": "text",
    "website": "text",
    "invoicecollection": "text",
    "compliance-partner": "category",
    "risk-value": "category",
    "prop-manager": "text",
    "email": "email",
    "phone": "phone",
    "client-status": "category",
    "services-interested-in": "category",

    # Campos de Tasks
    "titulo": "text",
    "description": "text",
    "status": "category",
    "deadline": "date",
}


def convert_value_for_podio(field_id, value):
    field_type = PODIO_FIELD_TYPES.get(field_id, "text")

    if field_type == "text":
        return {"value": str(value)} if value is not None else None

    if field_type == "category":
        if value is None:
            return None
        return {"value": str(value)}

    if field_type == "number":
        if value is None:
            return None
        return {"value": float(value)}

    if field_type == "progress":
        if value is None:
            return None
        value_int = int(value)
        if not (0 <= value_int <= 100):
            raise ValueError("Progress must be between 0 and 100.")
        return {"value": value_int}

    if field_type == "date":
        if value is None:
            return None

        # Si entra date → convertir a datetime a medianoche
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day, 0, 0)

        if not isinstance(value, datetime):
            raise ValueError("Date fields must be datetime or date.")

        return {
            "start": value.strftime("%Y-%m-%d %H:%M:%S")
        }

    if field_type == "email":
        if value is None:
            return None
        return {"value": str(value)}

    if field_type == "phone":
        if value is None:
            return None
        return {"value": str(value)}

    if field_type == "contact":
        if value is None:
            return None
        return {"value": int(value)}  # profile_id

    if field_type == "app":
        if value is None:
            return None
        return {"value": int(value)}  # item_id de otro item

    if field_type == "location":
        if value is None:
            return None
        return {"value": str(value)}

    if field_type == "money":
        if value is None:
            return None
        #   {"value": 100, "currency": "EUR"}
        if isinstance(value, dict):
            return {
                "value": str(Decimal(value["value"])),
                "currency": value.get("currency", "USD")
            }

        return {
            "value": str(Decimal(value)),
            "currency": "USD"
        }

    if field_type == "calculation":
        if value is None:
            return None

        # Podio *ignora* el valor, pero no rompe si lo envías
        return {"value": float(value)}

    # Default (fallback)
    return {"value": value}
