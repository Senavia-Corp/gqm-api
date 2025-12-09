from datetime import date, datetime
from decimal import Decimal

PODIO_FIELD_TYPES = {
    # Campos de QID
    # ----- De Jobs
    "client-2": "app",
    "project-location-2": "location",
    "job-status-2": "category",
    "project-name-2": "text",
    "powtnwo": "text",
    "service-type-3": "category",
    "date-assigned-2": "date",
    "gqm-target-sold-pricing-2": "money",
    # FALTA LA RELACION CON MEMBER!!
    # ----- De Order
    "tech-1-formula-2": "money",
    "tech-2-formula": "money",
    # ----- De Estimate Cost
    "estimated-rent-total-2": "money",
    "estimated-material-total-2": "money",
    "estimated-city-permits-total": "money",
    "bldg-dept-fees-1": "money",
    "bldg-dept-fees-2": "money",
    "bldg-dept-fees-3": "money",
    "purchase-1": "money",
    "purchase-2": "money",
    "purchase-3": "money",
    # ----- De Change Orders
    "": "money",


    # Campos de PTL
    # ----- De Jobs
    "client": "app",
    "location": "location",
    "categoria": "category",  # Esto es status
    "estimated-start-date": "date",
    "ptl-cost": "money",  # Target sold pricing
    # FALTA LA RELACION CON MEMBER!!
    # ----- De Order
    "tech-1-ptl-original-pricing": "money",
    "tech-1-ptl-original-pricing-2": "money",
    # ----- De Estimate Cost
    "gc-fee-if-applicable-2": "money",
    "gqm-estimated-material-total": "money",
    "tech-1-hd-materials": "money",
    "tech-2-hd-materials": "money",
    # ----- De Change Orders
    "": "money",


    # Campos de PAR
    # ----- De Jobs
    "client": "app",
    "week-assigned": "date",
    "job-status": "category",
    "gqm-target-sold-par": "money",
    # ----- De Order
    "tech-1-formula": "money",
    "tech-2-formula": "money",

    # Campos de Clients
    "titulo": "text",
    "address": "location",
    "parent-company": "text",
    "website-2": "embed",
    "invoicecollection": "text",
    "compliance-partner": "category",
    "risk-value": "category",
    "prop-manager": "text",
    "email": "email",
    "phone": "phone",
    "client-status": "category",
    "services-interested-in": "category",
    # FALTA LA RELACION CON parent-mgmt-company!!!

    # Campos de Tasks
    "titulo": "text",  # Name en mi modelo
    "description": "text",
    "status": "category",
    "deadline": "date",  # Delivery_date en mi modelo
    "related-project": "app",
}


def convert_value_for_podio(field_id, value):
    field_type = PODIO_FIELD_TYPES.get(field_id, "text")

    if field_type == "app":
        return {"value": int(value)} if value else None

    if field_type == "text":
        return {"value": str(value)} if value is not None else None

    if field_type == "category":
        if value is None:
            return None
        return {"value": str(value)}

    if field_type == "embed":
        if value is None:
            return None

        # Caso 1: te pasan directamente la URL como string
        if isinstance(value, str):
            url = value.strip()
            if not url:
                return None
            return {"url": url}

        # Caso 2: dict con una URL {"url": "..."}
        if isinstance(value, dict) and "url" in value:
            url = value.get("url")
            if not url:
                return None
            return {"url": str(url)}

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
        return [{"type": "work", "value": str(value)}]

    if field_type == "phone":
        if value is None:
            return None
        return [{"type": "work", "value": str(value)}]

    if field_type == "contact":
        if value is None:
            return None
        return {"value": int(value)}  # profile_id

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
