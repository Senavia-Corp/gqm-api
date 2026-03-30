# ============ Lógica de rutas =================
from flask import Blueprint, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.CommissionModel import Commission, CommissionUpdate
from ..models.ComGroupModel import CommissionGroup
from sqlalchemy.orm import joinedload, load_only
from sqlalchemy import func, or_
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger

# Blueprint de Commission:
commission_bp = Blueprint("commission_blueprint",
                          __name__, url_prefix="/commission")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todas las commission
@commission_bp.get("/")
@handle_exceptions()
@paginate()
def list_commissions():

    with get_session() as session:
        statement = (
            select(Commission)
            .options(
                joinedload(Commission.member),
                joinedload(Commission.comgroups)
                .joinedload(CommissionGroup.comdetails)
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        commission_data = [
            add_relationships(
                commission, ["member", "comgroups.comdetails"])
            for commission in results]

        return commission_data, 200


# Ruta para conseguir la lista de todas las commission con datos específicos
@commission_bp.get("/commission_table")
@handle_exceptions()
def list_commission_table():

    page = max(1, int(request.args.get("page",  1)))
    limit = min(200, max(1, int(request.args.get("limit", 10))))
    q = request.args.get("q", "").strip()

    with get_session() as session:

        # ── Base statement ─────────────────────────────────────────────────
        stmt = (
            select(Commission)
            .options(
                load_only(
                    Commission.ID_Commission,
                    Commission.Month,
                    Commission.Year,
                    Commission.Total_commission
                )
            )
        )

        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Commission.ID_Commission.ilike(pattern),
                    Commission.Month.ilike(pattern),
                    Commission.Year.ilike(pattern),
                )
            )

        # ── Total ──────────────────────────────────────────────────────────
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()

        # ── Paginación SQL ─────────────────────────────────────────────────
        offset = (page - 1) * limit
        stmt = stmt.order_by(Commission.ID_Commission.desc()).offset(
            offset).limit(limit)
        results = session.exec(stmt).all()

        # ── Serializar ─────────────────────────────────────────────────────
        rows = [
            {
                "ID_Commission": s.ID_Commission,
                "Month": s.Month,
                "Year": s.Year,
                "Total_commission": s.Total_commission,
            }
            for s in results
        ]

        return {
            "page":    page,
            "limit":   limit,
            "total":   total,
            "results": rows,
        }, 200


# Ruta para conseguir una commission por ID
@commission_bp.get("/<id_commission>")
@handle_exceptions()
def get_commission(id_commission):

    with get_session() as session:
        statement = (
            select(Commission)
            .options(
                joinedload(Commission.member),
                joinedload(Commission.comgroups)
                .joinedload(CommissionGroup.comdetails)
            )
            .where(Commission.ID_Commission == id_commission)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Commission no encontrado.",
                               "commission_not_found", 404)

        commission_data = add_relationships(
            obj, ["member", "comgroups.comdetails"])

        return commission_data, 200


# Ruta para conseguir una commission por ID_Member
@commission_bp.get("/member/<id_member>")
@handle_exceptions()
def get_commissions_by_member(id_member):

    with get_session() as session:
        statement = (
            select(Commission)
            .options(
                joinedload(Commission.member),
                joinedload(Commission.comgroups)
                .joinedload(CommissionGroup.comdetails)
            )
            .where(Commission.ID_Member == id_member)
        )

        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        commission_data = [
            add_relationships(
                commission, ["member", "comgroups.comdetails"])
            for commission in results
        ]

        return commission_data, 200


# --------------- RUTA PATCH --------------- #
# Ruta para actualizar una commission
@commission_bp.patch("/<commission_id>")
@handle_exceptions()
def update_commission(commission_id):

    data = request.get_json()

    with get_session() as session:
        obj = session.exec(
            select(Commission).where(
                Commission.ID_Commission == commission_id)
        ).first()
        if not obj:
            raise AppException("Commission no encontrado.",
                               "commission_not_found", 404)

        update_commission = CommissionUpdate.model_validate(data)
        update_data_dict = update_commission.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info("🔄 Commission actualizado | commission_id=%s",
                    commission_id)

        return obj.model_dump(), 200
