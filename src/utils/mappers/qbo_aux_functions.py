from src.models.FinancialDocModel import DocumentType
# Extraer valor del JSON


def extract_value(obj: dict, path: str):
    if not obj or not path:
        return None

    value = obj

    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
        if value is None:
            return None

    return value


# Calcular el porcentaje pagado
def calculate_percentage_paid(total, balance):
    # Convertimos a float por seguridad
    total = float(total or 0)
    balance = float(balance or 0)

    if total <= 0:
        return 0.0  # Evita división por cero si la factura está en 0

    amount_paid = total - balance
    percentage_paid = (amount_paid / total) * 100

    return round(percentage_paid, 2)  # Lo redondeamos a 2 decimales


# Agregar la relación con Job
def attach_job_code(mapped_doc: dict) -> dict:
    doc_number = mapped_doc.get("Job_Ref_QBO")

    if not doc_number:
        return mapped_doc

    job_code = doc_number.split("-")[0]
    mapped_doc["Job_Code"] = job_code

    return mapped_doc


# Agregar la relación con Client o Subcontractor dependiendo del documento
def attach_related_entity(mapped_doc: dict, raw_json: dict, doc_type):

    if doc_type == DocumentType.Invoice:
        customer = raw_json.get("CustomerRef", {})
        customer_name = customer.get("name")
        mapped_doc["Related_Name"] = customer_name
        mapped_doc["Related_Type"] = "client"

    elif doc_type == DocumentType.Bill:
        vendor = raw_json.get("VendorRef", {})
        vendor_name = vendor.get("name")
        mapped_doc["Related_Name"] = vendor_name
        mapped_doc["Related_Type"] = "subcontractor"

    return mapped_doc


# Extraer la relación entre documentos y sus pagos
def extract_linked_txn(qbo_obj):
    linked_txns = []

    # LinkedTxn está dentro de Line
    for line in qbo_obj.get("Line", []):
        line_links = line.get("LinkedTxn", [])
        if line_links:
            linked_txns.extend(line_links)

    return linked_txns
