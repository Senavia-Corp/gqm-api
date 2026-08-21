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
    """Crea o ACTUALIZA una linea de documento financiero.

    Se llamaba "upsert" y solo hacia insert: no habia ni un SELECT previo, asi
    que cada pasada creaba filas nuevas.

    Los dos llamadores se comportaban distinto y por eso el fallo no era
    evidente:

      · `src/quickbooks/webhook/functions.py:166` y `:235` BORRAN todas las
        lineas del documento antes de reinsertar. Ese camino es idempotente y
        nunca duplico.
      · `src/quickbooks/sync/sync_invoices_with_payments.py:136` recorre las
        lineas y llama SIN borrar antes. Ese es el que duplicaba, y una vez por
        cada pasada del sync masivo.

    Medido en PRODUCCION el 21-ago-2026:

        463 pares duplicados · 233 documentos · 485 filas sobrantes
        $298.479,99 de mas

    Y no eran solo dobles: FD60023 tiene su linea 1 TRIPLICADA (FDI60055,
    FDI60881, FDI67843), asi que el sync masivo corrio al menos tres veces. La
    cabecera del documento queda bien, asi que el descuadre solo se ve abriendo
    el detalle — donde lo ve el cliente.

    La clave natural es `(ID_FinancialDoc, qbo_line_id)`: `qbo_line_id` es el
    `Id` de la linea en QuickBooks (`QBO_FDOCITEM_INVOICE_FIELD_MAP`), unico
    dentro de su documento. Verificado en produccion: las 7.603 filas lo tienen
    (0 nulos), asi que la clave sirve para todas.

    Arreglar esto NO limpia las 485 filas que ya existen — eso es un DELETE
    sobre datos financieros de produccion y necesita respaldo y autorizacion.
    Pero sin este arreglo, limpiar no sirve de nada: la siguiente pasada vuelve
    a llenarlo.

    Mismo patron que `upsert_financial_transaction`, 20 lineas mas abajo.
    """
    qbo_line_id = data.get("qbo_line_id")

    # ---------  🔍 BUSCAR EXISTENCIA POR (documento, linea de QBO)
    existing = None
    if qbo_line_id is not None:
        existing = session.exec(
            select(FinancialDoc_Item).where(
                FinancialDoc_Item.ID_FinancialDoc == doc_id,
                FinancialDoc_Item.qbo_line_id == qbo_line_id,
            )
        ).first()

    # ---------  🔁 UPDATE
    if existing:
        changed = False
        for field, value in data.items():
            if getattr(existing, field, None) != value:
                setattr(existing, field, value)
                changed = True

        if changed and not dry_run:
            session.add(existing)
            session.flush()

        return existing, False

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
