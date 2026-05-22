from flask import Blueprint, jsonify, request
from ...database.db_sqlmodel import get_session
from ...models.FinancialDocModel import FinancialDocument
from ...models.FinancialTransModel import FinancialTransaction
from ...models.link_models.FinancialLink import FinancialLink
from sqlmodel import select


# ------------------- Link entre FDocument y FTransaction -------------------
fdocument_ftransaction_bp = Blueprint(
    "fdocument_ftransaction_blueprint", __name__, url_prefix="/fdocument_ftransaction")

def _recalculate_doc_balances(session, fdocument: FinancialDocument):
    # Calcular sumatoria de amount_applied
    statement = select(FinancialLink).where(FinancialLink.fdocument_id == fdocument.ID_FinancialDoc)
    links = session.exec(statement).all()
    
    total_paid = sum((l.amount_applied or 0.0) for l in links)
    total_amount = fdocument.Total_Amount or 0.0
    
    fdocument.Balance_Amount = total_amount - total_paid
    if total_amount > 0:
        fdocument.Percentage_Paid = round((total_paid / total_amount) * 100, 2)
    else:
        fdocument.Percentage_Paid = 0.0
        
    session.add(fdocument)


# Vincular un document con una transaction
@fdocument_ftransaction_bp.post("/fdocument/<fdocument_id>/ftransaction/<ftransaction_id>")
def assign_doc_to_trans(fdocument_id, ftransaction_id):
    # Get amount_applied from request body if exists
    data = request.get_json(silent=True) or {}
    amount_applied = data.get("amount_applied", None)
    
    with get_session() as session:
        fdocument = session.get(FinancialDocument, fdocument_id)
        ftransaction = session.get(FinancialTransaction, ftransaction_id)

        if not fdocument or not ftransaction:
            return jsonify({"error": "Financial Document or Financial Transaction not found"}), 404

        existing_link = session.get(
            FinancialLink, (fdocument_id, ftransaction_id))
        
        if existing_link:
            # Actualizar amount_applied si se envió uno nuevo
            if amount_applied is not None:
                existing_link.amount_applied = amount_applied
                session.add(existing_link)
                _recalculate_doc_balances(session, fdocument)
                session.commit()
                return jsonify({"status": "Link updated ✔️"}), 200
            return jsonify({"status": "Already linked ✔️"}), 200

        # Si no existe, crear el link
        # Si no mandaron amount_applied, usamos el Total_Amount del transaction o lo que falte
        if amount_applied is None:
            # Default behavior: apply the transaction's total amount
            amount_applied = ftransaction.Total_Amount or 0.0

        link = FinancialLink(
            fdocument_id=fdocument_id,
            ftransaction_id=ftransaction_id,
            amount_applied=amount_applied
        )

        session.add(link)
        session.flush() # Para poder recalcular con el link guardado en DB (o agregarlo a fdocument)
        
        _recalculate_doc_balances(session, fdocument)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "fdocument_id": fdocument_id,
            "ftransaction_id": ftransaction_id,
            "amount_applied": amount_applied
        }), 201


# Desvincular un document de una transaction
@fdocument_ftransaction_bp.delete("/fdocument/<fdocument_id>/ftransaction/<ftransaction_id>")
def remove_doc_from_trans(fdocument_id, ftransaction_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            FinancialLink,
            (fdocument_id, ftransaction_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404
            
        fdocument = session.get(FinancialDocument, fdocument_id)

        session.delete(link)
        session.flush() # Delete it before recalculating
        
        if fdocument:
            _recalculate_doc_balances(session, fdocument)
            
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "fdocument_id": fdocument_id,
            "ftransaction_id": ftransaction_id
        }), 200
