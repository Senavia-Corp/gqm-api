# ============ Lógica de rutas =================
from datetime import datetime

from flask import Blueprint, Response, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.CommissionModel import Commission, CommissionUpdate
from ..models.ComGroupModel import CommissionGroup
from ..models.ComDetailModel import CommissionDetail
from ..models.MemberModel import Member
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload, load_only, selectinload
from sqlalchemy import func, or_
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..services.excel_report.commission_excel_service import generate_commission_excel
from ..utils.middleware.auth.routes_protection import get_user_context, require_permission
from ..utils.policy_evaluator import PolicyEvaluator

# Blueprint de Commission:
commission_bp = Blueprint("commission_blueprint",
                          __name__, url_prefix="/commission")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todas las commission
@commission_bp.get("/")
@require_permission(["commission:read", "commission:read_own"])
@handle_exceptions()
@paginate()
def list_commissions():

    user_id, _user_type, policies = get_user_context()
    can_read_all = PolicyEvaluator.evaluate(policies, "commission:read")
    can_read_own = PolicyEvaluator.evaluate(policies, "commission:read_own")
    filter_own = user_id and can_read_own and not can_read_all

    with get_session() as session:
        statement = (
            select(Commission)
            .options(
                joinedload(Commission.member),
                joinedload(Commission.comgroups)
                .joinedload(CommissionGroup.comdetails)
            )
        )

        if filter_own:
            statement = statement.where(Commission.ID_Member == user_id)

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
@require_permission(["commission:read", "commission:read_own"])
@handle_exceptions()
def list_commission_table():

    page = max(1, int(request.args.get("page",  1)))
    limit = min(200, max(1, int(request.args.get("limit", 10))))
    q = request.args.get("q", "").strip()

    # Determine if the requesting user is restricted to their own commissions.
    # Users with commission:read see everything; users with commission:read_own
    # (and without commission:read) only see commissions linked to their member ID.
    user_id, _user_type, policies = get_user_context()
    can_read_all = PolicyEvaluator.evaluate(policies, "commission:read")
    can_read_own = PolicyEvaluator.evaluate(policies, "commission:read_own")
    filter_own = user_id and can_read_own and not can_read_all

    with get_session() as session:

        stmt = (
            select(Commission)
            .options(
                load_only(
                    Commission.ID_Commission,
                    Commission.Month,
                    Commission.Year,
                    Commission.Total_commission,
                    Commission.ID_Member,
                ),
                selectinload(Commission.member).load_only(
                    Member.ID_Member,
                    Member.Member_Name,
                )
            )
        )

        if filter_own:
            stmt = stmt.where(Commission.ID_Member == user_id)

        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Commission.ID_Commission.ilike(pattern),
                    Commission.Month.ilike(pattern),
                    Commission.Year.ilike(pattern),
                    Commission.Total_commission.ilike(pattern),
                    Member.Member_Name.ilike(pattern),
                )
            )
            stmt = stmt.join(Commission.member, isouter=True)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()

        offset = (page - 1) * limit
        stmt = stmt.order_by(Commission.ID_Commission.desc()).offset(offset).limit(limit)
        results = session.exec(stmt).all()

        rows = [
            {
                "ID_Commission":    s.ID_Commission,
                "Month":            s.Month,
                "Year":             s.Year,
                "Total_commission": s.Total_commission,
                "member": {
                    "ID_Member":   s.member.ID_Member,
                    "Member_Name": s.member.Member_Name,
                } if s.member else None,
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
@require_permission(["commission:read", "commission:read_own"])
@handle_exceptions()
def get_commission(id_commission):

    user_id, _user_type, policies = get_user_context()
    can_read_all = PolicyEvaluator.evaluate(policies, "commission:read")
    can_read_own = PolicyEvaluator.evaluate(policies, "commission:read_own")
    filter_own = user_id and can_read_own and not can_read_all

    with get_session() as session:
        statement = (
            select(Commission)
            .options(
                joinedload(Commission.member),
                joinedload(Commission.comgroups)
                .joinedload(CommissionGroup.comdetails).joinedload(CommissionDetail.job)
            )
            .where(Commission.ID_Commission == id_commission)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Commission no encontrado.",
                               "commission_not_found", 404)

        if filter_own and obj.ID_Member != user_id:
            raise AppException("Forbidden: you can only view your own commissions.",
                               "commission_forbidden", 403)

        commission_data = add_relationships(
            obj, ["member", "comgroups.comdetails", "comgroups.comdetails.job"])

        return commission_data, 200


# Ruta para conseguir una commission por ID_Member
@commission_bp.get("/member/<id_member>")
@require_permission(["commission:read", "commission:read_own"])
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
@require_permission("commission:update")
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


# --------------- RUTA GET Excel --------------- #
@commission_bp.get("/excel")
@require_permission(["commission:read", "commission:read_own"])
@handle_exceptions()
def export_commissions_excel():
    member_ids = request.args.getlist("member_id") or None
    year = request.args.get("year", type=int)
    month = request.args.get("month")

    with get_session() as session:
        data = generate_commission_excel(session, member_ids, year, month)

    filename = f"commissions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
