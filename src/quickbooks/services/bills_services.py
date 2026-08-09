
from .qbo_base_services import qbo_query


# GET para Bills
def get_bills(realm_id, start=1, limit=100):

    query = (
        "SELECT * FROM Bill "
        "ORDER BY Metadata.LastUpdatedTime DESC "
    )

    return qbo_query(realm_id, query, start=start, limit=limit)


# GET Bill por Job
def get_bill_by_job(realm_id, job_code, start=1, limit=100):

    from src.quickbooks.services.qbo_validation import validate_job_code
    job_code = validate_job_code(job_code)
    query = (
        f"SELECT * FROM Bill WHERE DocNumber LIKE '{job_code}-%'"
    )

    return qbo_query(realm_id, query, start=start, limit=limit)
