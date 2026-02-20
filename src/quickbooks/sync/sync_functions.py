from sqlmodel import select
from src.utils.id_generator import generate_custom_id
from src.utils.mappers.clean_podio_fields import normalize_name
from src.models.FinancialDocModel import FinancialDocument
from src.models.FinancialDocItemModel import FinancialDoc_Item
from src.models.FinancialTransModel import FinancialTransaction
from src.models.link_models.FinancialLink import FinancialLink
from src.models.JobModel import Job
from src.models.ClientModel import Client
from src.models.SubcontractorModel import Subcontractor
from src.models.FinancialDocModel import DocumentType


# -------------------------- SINCRONIZAR FINANCIAL DOCUMENTS -------------------------- #
def upsert_financial_document(session, data, doc_type, dry_run=False):

    print("\n==============================")
    print("🚀 UPSERT FINANCIAL DOCUMENT")
    print("==============================")
    print("📄 Doc Type:", doc_type)

    # ---------  🔗 RELACIÓN CON JOB
    job_code = data.pop("Job_Code", None)

    print("🔎 Extracted Job_Code:", job_code)

    job_obj = None

    if job_code:
        print("🔍 Buscando Job en DB...")
        job_obj = session.exec(
            select(Job).where(Job.ID_Jobs == job_code)
        ).first()

        if job_obj:
            print(f"✅ Job encontrado → ID_Jobs: {job_obj.ID_Jobs}")
        else:
            print("⚠️ Job NO encontrado en DB")
    else:
        print("ℹ️ No hay Job_Code en data")

    # ---------  🔗 RELACIÓN CON CLIENTE O SUBCONTRACTOR
    client_obj = None
    subcontractor_obj = None

    print("🔎 Buscando Cliente/Subcontractor según doc_type...")

    if doc_type == DocumentType.Invoice:
        customer_ref = data.get("CustomerRef")
        if customer_ref and customer_ref.get("name"):
            related_name = customer_ref.get("name")
            normalized_qbo_name = normalize_name(related_name)
            print(
                f"🔎 Invoice: Buscando Cliente → {related_name} (normalizado: {normalized_qbo_name})")

            clients = session.exec(select(Client)).all()
            for client in clients:
                normalized_db_name = normalize_name(client.Client_Community)
                if normalized_db_name == normalized_qbo_name:
                    client_obj = client
                    break

            if client_obj:
                print(f"✅ Client encontrado: {client_obj.ID_Client}")
            else:
                print("⚠️ Client NO encontrado")
        else:
            print("ℹ️ Invoice sin CustomerRef.name, saltando búsqueda de cliente")

    elif doc_type == DocumentType.Bill:
        vendor_ref = data.get("VendorRef")
        if vendor_ref and vendor_ref.get("name"):
            related_name = vendor_ref.get("name")
            normalized_qbo_name = normalize_name(related_name)
            print(
                f"🔎 Bill: Buscando Subcontractor → {related_name} (normalizado: {normalized_qbo_name})")

            subcontractors = session.exec(select(Subcontractor)).all()
            for sub in subcontractors:
                normalized_db_name = normalize_name(sub.Organization)
                if normalized_db_name == normalized_qbo_name:
                    subcontractor_obj = sub
                    break

            if subcontractor_obj:
                print(
                    f"✅ Subcontractor encontrado: {subcontractor_obj.ID_Subcontractor}")
            else:
                print("⚠️ Subcontractor NO encontrado")
        else:
            print("ℹ️ Bill sin VendorRef.name, saltando búsqueda de subcontractor")

    else:
        print("⏭️ Saltando búsqueda: no hay relación con estas entidades.")

    # ---------  🔍 BUSCAR EXISTENCIA POR QBO ID
    print("🔎 Buscando documento existente por qbo_id...")

    existing = session.exec(
        select(FinancialDocument).where(
            FinancialDocument.qbo_id == data["qbo_id"]
        )
    ).first()

    # ---------  🔁 UPDATE
    if existing:

        print(f"🔁 Documento existente encontrado → {existing.ID_FinancialDoc}")
        changed = False

        for field, value in data.items():
            current_value = getattr(existing, field)

            if getattr(existing, field) != value:
                print(f"✏️ Campo cambiado: {field}")
                print(f"    Antes: {current_value}")
                print(f"    Nuevo: {value}")
                setattr(existing, field, value)
                changed = True

        if existing.Type_of_document != doc_type:
            print("✏️ Actualizando Type_of_document")
            existing.Type_of_document = doc_type
            changed = True

        if job_obj and existing.ID_Jobs != job_obj.ID_Jobs:
            print("🔗 Actualizando relación con Job")
            existing.ID_Jobs = job_obj.ID_Jobs
            changed = True

        if client_obj and existing.ID_Client != client_obj.ID_Client:
            print("🔗 Actualizando relación con Client")
            existing.ID_Client = client_obj.ID_Client
            changed = True

        if subcontractor_obj and existing.ID_Subcontractor != subcontractor_obj.ID_Subcontractor:
            print("🔗 Actualizando relación con Subcontractor")
            existing.ID_Subcontractor = subcontractor_obj.ID_Subcontractor
            changed = True

        if changed and not dry_run:
            session.add(existing)
            print("✅ Documento actualizado en sesión")

        return existing, False

    # ---------  🆕 CREATE
    print("🆕 Documento NO existe → creando nuevo")

    new_id = generate_custom_id(
        session, FinancialDocument, "ID_FinancialDoc", "FD")

    new_doc = FinancialDocument(
        ID_FinancialDoc=new_id,
        Type_of_document=doc_type,
        ID_Jobs=job_obj.ID_Jobs if job_obj else None,
        ID_Client=client_obj.ID_Client if client_obj else None,
        ID_Subcontractor=subcontractor_obj.ID_Subcontractor if subcontractor_obj else None,
        **data
    )

    if not dry_run:
        session.add(new_doc)
        session.flush()
        print("✅ Nuevo documento agregado.")

    return new_doc, True


# -------------------------- SINCRONIZAR FINANCIAL DOC ITEMS -------------------------- #
def upsert_financial_doc_items(session, data, doc_id, dry_run=False):

    # ---------  🔍 BUSCAR EXISTENCIA POR QBO ID
    existing = session.exec(
        select(FinancialDoc_Item).where(
            FinancialDoc_Item.ID_FinancialDoc == doc_id,
            FinancialDoc_Item.qbo_line_id == data["qbo_line_id"]
        )
    ).first()

    # ---------  🔁 UPDATE
    if existing:

        changed = False

        for field, value in data.items():
            if getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True

        if changed and not dry_run:
            session.add(existing)

        return existing, False

    # ---------  🆕 CREATE
    new_id = generate_custom_id(session, FinancialDoc_Item, "ID_FDItem", "FDI")

    new_doc_item = FinancialDoc_Item(
        ID_FDItem=new_id,
        ID_FinancialDoc=doc_id,
        **data
    )

    if not dry_run:
        session.add(new_doc_item)
        session.flush()

    return new_doc_item, True


# -------------------------- SINCRONIZAR FINANCIAL TRANSACTIONS -------------------------- #
def upsert_financial_transaction(session, data, trans_type, dry_run=False):

    print("\n==============================")
    print("🚀 UPSERT FINANCIAL TRANSACTION")
    print("================================")
    print(f"   Tipo esperado: {trans_type}")

    # ---------  🔍 BUSCAR EXISTENCIA POR QBO ID
    existing = session.exec(
        select(FinancialTransaction).where(
            FinancialTransaction.qbo_id == data["qbo_id"]
        )
    ).first()

    # ---------  🔁 UPDATE
    if existing:

        print(f"   ➡️   EXISTE en DB: {existing.ID_FTransaction}")
        changed = False

        for field, value in data.items():
            current_value = getattr(existing, field)

            if current_value != value:
                print(f"      ✏️ Campo cambiado: {field}")
                print(f"         Antes: {current_value}")
                print(f"         Ahora: {value}")
                setattr(existing, field, value)
                changed = True

        if existing.Type_of_transaction != trans_type:
            print("✏️ Actualizando Type_of_transaction")
            existing.Type_of_transaction = trans_type
            changed = True

        if changed and not dry_run:
            session.add(existing)

        return existing, False

    # ---------  🆕 CREATE
    print("🆕    Transacción NO existe → creando nueva")

    new_id = generate_custom_id(
        session, FinancialTransaction, "ID_FTransaction", "FT")

    new_trans = FinancialTransaction(
        ID_FTransaction=new_id,
        Type_of_transaction=trans_type,
        **data
    )

    if not dry_run:
        session.add(new_trans)
        session.flush()
        print("✅ Nueva transacción agregada.")

    return new_trans, True


# -------------------------- SINCRONIZAR FINANCIAL LINK -------------------------- #
def upsert_financial_link(session, doc_id, trans_id, dry_run=False):

    print("\n🔗 [LINK] Intentando vincular:")
    print(f"   Documento ID: {doc_id}")
    print(f"   Transaction ID: {trans_id}")

    existing = session.exec(
        select(FinancialLink).where(
            FinancialLink.fdocument_id == doc_id,
            FinancialLink.ftransaction_id == trans_id
        )
    ).first()

    if existing:
        print(" ℹ️   LINK ya existe. No se crea nuevo.")
        return existing, False  # ya existía

    print(" ➕  LINK no existe. Creando...")

    new_link = FinancialLink(
        fdocument_id=doc_id,
        ftransaction_id=trans_id
    )

    if not dry_run:
        session.add(new_link)
        session.flush()
        print("✅ Nuevo link agregado.")

    return new_link, True  # creado
