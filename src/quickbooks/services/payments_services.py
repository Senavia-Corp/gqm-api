
from .qbo_base_services import qbo_query


# ------------------------------------------------- #
# ------------------- INVOICES -------------------- #

# GET para Invoice Payments
def get_money_received(realm_id, start=1, limit=200):

    query = (
        f"SELECT * FROM Payment ORDER BY TxnDate DESC"
    )

    return qbo_query(realm_id, query, start=start, limit=limit)


# ------------------------------------------------- #
# --------------------- BILLS --------------------- #

# GET para Bill Payments
def get_bill_payments(realm_id, start=1, limit=200):

    query = (
        f"SELECT * FROM BillPayment ORDER BY TxnDate DESC"
    )

    return qbo_query(realm_id, query, start=start, limit=limit)
