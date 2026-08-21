from sqlmodel import select
from datetime import date
from src.utils.id_generator import generate_custom_id
from src.models.FinancialDocModel import FinancialDocument
from src.models.FinancialDocItemModel import FinancialDoc_Item
from src.models.FinancialTransModel import FinancialTransaction
from src.models.link_models.FinancialLink import FinancialLink
from src.models.JobModel import Job


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

        if changed and not dry_run:
            session.add(existing)
            print("✅ Documento actualizado en sesión")

        return existing, False

    # ---------  🆕 CREATE
    print("🆕 Documento NO existe → creando nuevo")

    # dry_run no puede tener efectos: `generate_custom_id` ya no es un SELECT
    # sin consecuencias — desde c5a8e3f24b17 reserva en `id_counters` y
    # commitea en su propia conexion, fuera de la transaccion del llamador.
    new_id = "FD-DRYRUN" if dry_run else generate_custom_id(
        session, FinancialDocument, "ID_FinancialDoc", "FD")

    new_doc = FinancialDocument(
        ID_FinancialDoc=new_id,
        Type_of_document=doc_type,
        ID_Jobs=job_obj.ID_Jobs if job_obj else None,
        **data
    )

    if not dry_run:
        session.add(new_doc)
        session.flush()
        print("✅ Nuevo documento agregado.")

    return new_doc, True


# -------------------------- SINCRONIZAR FINANCIAL DOC ITEMS -------------------------- #
def upsert_financial_doc_items(session, data, doc_id, dry_run=False):

    # ---------  🆕 CREATE
    # dry_run no puede tener efectos: `generate_custom_id` ya no es un SELECT
    # sin consecuencias — desde c5a8e3f24b17 reserva en `id_counters` y
    # commitea en su propia conexion, fuera de la transaccion del llamador.
    new_id = "FDI-DRYRUN" if dry_run else generate_custom_id(
        session, FinancialDoc_Item, "ID_FDItem", "FDI")

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

    # dry_run no puede tener efectos: `generate_custom_id` ya no es un SELECT
    # sin consecuencias — desde c5a8e3f24b17 reserva en `id_counters` y
    # commitea en su propia conexion, fuera de la transaccion del llamador.
    new_id = "FT-DRYRUN" if dry_run else generate_custom_id(
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
def upsert_financial_link(
    session,
    doc_id: str,
    trans_id: str,
    amount_applied: float | None = None,
    date_applied: date | None = None,
    dry_run: bool = False,
):

    print("\n🔗 [LINK] Intentando vincular:")
    print(f"   Documento ID: {doc_id}")
    print(f"   Transaction ID: {trans_id}")
    print(f"   Amount Applied:  {amount_applied}")
    print(f"   Date Applied:    {date_applied}")

    existing = session.exec(
        select(FinancialLink).where(
            FinancialLink.fdocument_id == doc_id,
            FinancialLink.ftransaction_id == trans_id
        )
    ).first()

    if existing:
        # Actualizar amount_applied y date_applied si cambiaron
        changed = False

        if amount_applied is not None and existing.amount_applied != amount_applied:
            print(
                f"   ✏️ Actualizando amount_applied: {existing.amount_applied} → {amount_applied}")
            existing.amount_applied = amount_applied
            changed = True

        if date_applied is not None and existing.date_applied != date_applied:
            print(
                f"   ✏️ Actualizando date_applied: {existing.date_applied} → {date_applied}")
            existing.date_applied = date_applied
            changed = True

        if changed and not dry_run:
            session.add(existing)
            print("   ✅ Link actualizado.")
        else:
            print("   ℹ️ Link ya existe y no hay cambios.")

        return existing, False

    print(" ➕  LINK no existe. Creando...")

    new_link = FinancialLink(
        fdocument_id=doc_id,
        ftransaction_id=trans_id,
        amount_applied=amount_applied,
        date_applied=date_applied,
    )

    if not dry_run:
        session.add(new_link)
        session.flush()
        print("✅ Nuevo link agregado.")

    return new_link, True  # creado
