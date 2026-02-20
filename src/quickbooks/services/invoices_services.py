
from .qbo_base_services import qbo_query


# Obtener todos los invoices
def get_invoices(realm_id, start=1, limit=200):

    query = (
        "SELECT * FROM Invoice "
        "ORDER BY Metadata.LastUpdatedTime DESC "
    )

    return qbo_query(realm_id, query, start=start, limit=limit)


# Obtener Invoice por Job
def get_invoices_by_job(realm_id, job_code, start=1, limit=100):

    query = (
        f"SELECT * FROM Invoice WHERE DocNumber LIKE '{job_code}-%'"
    )

    return qbo_query(realm_id, query, start=start, limit=limit)
