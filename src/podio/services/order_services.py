from sqlmodel import select
from src.models.OrderModel import Order

TECH_FORMULA_FIELDS = {
    "QID": {
        1: "tech-1-formula-2",
        2: "tech-2-formula",
    },
    "PTL": {
        1: "tech-1-ptl-original-pricing",
        2: "tech-1-ptl-original-pricing-2",
    },
    "PAR": {
        1: "tech-1-formula",
        2: "tech-2-formula",
    }
}


def get_next_available_tech_field(session, job_podio_id: str, job_type: str) -> str:
    job_type = job_type.upper()

    # 1. Traer Orders del mismo Job
    stmt = select(Order).where(Order.job_podio_id == job_podio_id)
    orders = session.exec(stmt).all()

    # 2. Campos ya usados
    used_fields = {o.tech_field for o in orders if o.tech_field}

    # 3. Buscar el primer TECH disponible
    for external_id in TECH_FORMULA_FIELDS[job_type].values():
        if external_id not in used_fields:
            return external_id

    # 4. Sin espacio
    raise ValueError(f"No hay más campos TECH disponibles para {job_type}")
