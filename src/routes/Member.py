# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.MemberModel import Member, MemberCreate, MemberUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload, load_only
from sqlalchemy import func, or_
from ..utils.middleware.auth.password_hashing import hash_password
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger

# Blueprint de Member:
member_bp = Blueprint("member_blueprint", __name__, url_prefix="/member")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los miembros GQM
@member_bp.get("/")
@handle_exceptions()
@paginate()  # decorador de paginación
def list_members():

    with get_session() as session:
        # Trae los miembros GQM con sus trabajos en una sola consulta
        statement = (
            select(Member)
            .options(
                joinedload(Member.jobs),
                joinedload(Member.permissions),
                joinedload(Member.role),
                joinedload(Member.tlactivity),
                joinedload(Member.commissions),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        member_data = []

        for member in results:
            data = add_relationships(
                member, ["jobs", "permissions", "role", "tlactivity", "commissions"])
            member_data.append(data)

        return member_data, 200


# Ruta para conseguir un miembro GQM por ID_Member
@member_bp.get("/<id_member>")
@handle_exceptions()
def get_member_by_id(id_member):

    with get_session() as session:
        statement = (
            select(Member)
            .options(
                joinedload(Member.jobs),
                joinedload(Member.permissions),
                joinedload(Member.role),
                joinedload(Member.tlactivity),
                joinedload(Member.tlactivity),
            )
            .where(Member.ID_Member == id_member)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Member no encontrado.",
                               "member_not_found", 404)

        # Construir JSON limpio con la info de los jobs
        member_data = add_relationships(
            obj, ["jobs", "permissions", "role", "tlactivity", "commissions"])

        return jsonify(member_data), 200


@member_bp.get("/member_table")
@handle_exceptions()
def list_members_table():

    page = int(request.args.get("page",  1))
    limit = int(request.args.get("limit", 20))
    q = request.args.get("q", "").strip()

    if page < 1:
        page = 1
    if limit < 1:
        limit = 20
    limit = min(limit, 200)

    with get_session() as session:
        base_stmt = (
            select(Member)
            .options(
                load_only(
                    Member.ID_Member,
                    Member.Member_Name,
                    Member.Company_Role,
                    Member.Email_Address,
                    Member.Phone_Number,
                )
            )
        )

        # ── Global search ──────────────────────────────────────────────
        if q:
            pattern = f"%{q}%"
            base_stmt = base_stmt.where(
                or_(
                    func.lower(Member.ID_Member).like(func.lower(pattern)),
                    func.lower(Member.Member_Name).like(
                        func.lower(pattern)),
                    func.lower(Member.Company_Role).like(
                        func.lower(pattern)),
                    func.lower(Member.Email_Address).like(
                        func.lower(pattern)),
                    func.lower(Member.Phone_Number).like(
                        func.lower(pattern)),
                )
            )

        # ── Total count (respects search filter) ───────────────────────
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = session.exec(count_stmt).one()

        # ── Paginated results ──────────────────────────────────────────
        offset = (page - 1) * limit
        paged_stmt = base_stmt.order_by(
            Member.ID_Member.desc()).offset(offset).limit(limit)
        results = session.exec(paged_stmt).unique().all()

        out = [
            {
                "ID_Member":    m.ID_Member,
                "Member_Name":  m.Member_Name,
                "Company_Role": m.Company_Role,
                "Email_Address": m.Email_Address,
                "Phone_Number": m.Phone_Number,
            }
            for m in results
        ]

        return jsonify({
            "page":    page,
            "limit":   limit,
            "total":   total,
            "results": out,
        }), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un miembro GQM
@member_bp.post("/")
@handle_exceptions()
def create_member():

    data = request.get_json()
    create_member = MemberCreate.model_validate(data)
    obj = Member.model_validate(create_member)

    with get_session() as session:

        obj.Password = hash_password(obj.Password)  # Hash al password

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Member, "ID_Member", "MEM")
        obj.ID_Member = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Member creado | member_id=%s",
            obj.ID_Member
        )

        response = obj.model_dump()
        response.pop("Password", None)

        return response.model_dump(), 201


# Ruta para actualizar un miembro GQM
@member_bp.patch("/<id_member>")
@handle_exceptions()
def update_member(id_member):

    data = request.get_json()

    with get_session() as session:
        obj = session.get(Member, id_member)
        if not obj:
            raise AppException("Member no encontrado.",
                               "member_not_found", 404)

        update_member = MemberUpdate.model_validate(data)
        update_data_dict = update_member.model_dump(exclude_unset=True)

        # Hash al passsword si se actualiza
        if "Password" in update_data_dict:
            update_data_dict["Password"] = hash_password(
                update_data_dict["Password"]
            )

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "🔄 Member actualizado | member_id=%s",
            obj.ID_Member
        )

        response = obj.model_dump()
        response.pop("Password", None)

        return response.model_dump(), 200


# Ruta para eliminar un miembro GQM
@member_bp.delete("/<id_member>")
@handle_exceptions()
def delete_member(id_member):

    with get_session() as session:
        obj = session.get(Member, id_member)
        if not obj:
            raise AppException("Member no encontrado.",
                               "member_not_found", 404)

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ Member eliminado | member_id=%s",
            id_member
        )

        return jsonify({
            "message": f"Member {id_member} eliminado correctamente"
        }), 200
