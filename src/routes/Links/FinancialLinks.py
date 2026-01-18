from flask import Blueprint, jsonify
from ...database.db_sqlmodel import get_session
from ...models.FinancialDocModel import FinancialDocument
from ...models.FinancialTransModel import FinancialTransaction
from ...models.link_models.FinancialLink import FinancialLink


# ------------------- Link entre FDocument y FTransaction -------------------
fdocument_ftransaction_bp = Blueprint(
    "fdocument_ftransaction_blueprint", __name__, url_prefix="/fdocument_ftransaction")


# Vincular un document con una transaction
@fdocument_ftransaction_bp.post("/fdocument/<fdocument_id>/ftransaction/<ftransaction_id>")
def assign_doc_to_trans(fdocument_id, ftransaction_id):
    with get_session() as session:
        fdocument = session.get(FinancialDocument, fdocument_id)
        ftransaction = session.get(FinancialTransaction, ftransaction_id)

        if not fdocument or not ftransaction:
            return jsonify({"error": "Financial Document or Financial Transaction not found"}), 404

        existing_link = session.get(
            FinancialLink, (fdocument_id, ftransaction_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = FinancialLink(
            fdocument_id=fdocument_id,
            ftransaction_id=ftransaction_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "fdocument_id": fdocument_id,
            "ftransaction_id": ftransaction_id
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

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "fdocument_id": fdocument_id,
            "ftransaction_id": ftransaction_id
        }), 200
