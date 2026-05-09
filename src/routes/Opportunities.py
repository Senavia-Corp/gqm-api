from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy import or_
from datetime import datetime
from ..database.db_sqlmodel import get_session
from ..models.OpportunitiesModel import Opportunities, OpportunitiesCreate
from ..models.SubcontractorModel import Subcontractor
from ..models.SkillsModel import Skills
from ..models.link_models.OpportunitiesLinks import OpportSubcLink, OpportSkillsLink
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de Opportunities
opportunities_bp = Blueprint(
    "oppotunities_blueprint", __name__, url_prefix="/oppotunities")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos las opportunities
@opportunities_bp.get("/")
@paginate()
def list_opportunities():
    try:
        with get_session() as session:
            q = request.args.get("q", "").strip()
            state_filter = request.args.get("state", "").strip()
            priority_filter = request.args.get("priority", "").strip()
            job_id = request.args.get("job_id", "").strip()
            skill_id = request.args.get("skill_id", "").strip()
            subcontractor_id = request.args.get("subcontractor_id", "").strip()
            print(f"DEBUG: list_opportunities args: {request.args}")

            statement = (
                select(Opportunities)
                .options(
                    joinedload(Opportunities.job),
                    joinedload(Opportunities.skills),
                    joinedload(Opportunities.subcontractors),
                    joinedload(Opportunities.order),
                )
            )

            if skill_id and skill_id != "ALL":
                statement = statement.join(OpportSkillsLink, Opportunities.ID_Opportunities == OpportSkillsLink.opport_id).where(OpportSkillsLink.skills_id == skill_id)

            if q:
                pattern = f"%{q}%"
                statement = statement.where(
                    or_(
                        Opportunities.Project_name.ilike(pattern),
                        Opportunities.Description.ilike(pattern),
                        Opportunities.ID_Opportunities.ilike(pattern),
                        Opportunities.ID_Jobs.ilike(pattern),
                    )
                )

            if state_filter == "active":
                statement = statement.where(Opportunities.State == True)
            elif state_filter == "inactive":
                statement = statement.where(Opportunities.State == False)

            if priority_filter and priority_filter != "ALL":
                statement = statement.where(
                    Opportunities.Priority.ilike(priority_filter))
            
            if job_id:
                statement = statement.where(Opportunities.ID_Jobs == job_id)

            if subcontractor_id:
                statement = statement.where(Opportunities.subcontractors.any(Subcontractor.ID_Subcontractor == subcontractor_id))

            results = session.exec(statement).unique().all()

            if not results:
                return [], 200

            opport_data = []
            for opportunities in results:
                data = add_relationships(
                    opportunities, ["job", "skills", "subcontractors", "order"])
                data["applicants_count"] = len(opportunities.subcontractors) if opportunities.subcontractors else 0
                opport_data.append(data)

            return opport_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar opportunities: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar opportunities: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir una opportunity por ID
@opportunities_bp.get("/<id_opportunities>")
def get_opportunity(id_opportunities):
    try:
        with get_session() as session:

            statement = (
                select(Opportunities)
                .options(
                    joinedload(Opportunities.job),
                    joinedload(Opportunities.skills),
                    joinedload(Opportunities.subcontractors),
                    joinedload(Opportunities.order),
                )
                .where(Opportunities.ID_Opportunities == id_opportunities)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Opportunity not found"}), 404

            opport_data = add_relationships(
                obj, ["job", "skills", "subcontractors", "order"])

            return jsonify(opport_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar opportunity {id_opportunities}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar opportunities: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir los applicants (subcontratistas postulados) con su estado
@opportunities_bp.get("/<id_opportunities>/applicants")
def get_opportunity_applicants(id_opportunities):
    try:
        with get_session() as session:
            opportunity = session.get(Opportunities, id_opportunities)
            if not opportunity:
                return jsonify({"error": "Opportunity not found"}), 404

            links = session.exec(
                select(OpportSubcLink).where(
                    OpportSubcLink.opport_id == id_opportunities)
            ).all()

            result = []
            for link in links:
                subc = session.get(Subcontractor, link.subcon_id)
                if subc:
                    org = subc.Organization
                    if isinstance(org, list):
                        org = org[0] if org else None
                    result.append({
                        "ID_Subcontractor": subc.ID_Subcontractor,
                        "Name": subc.Name,
                        "Organization": str(org) if org else None,
                        "Email_Address": subc.Email_Address,
                        "Phone_Number": subc.Phone_Number,
                        "Status": subc.Status,
                        "Score": subc.Score,
                        "application_state": link.State,
                    })

            return jsonify(result), 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar applicants: {db_error}")
        return jsonify({"detail": "Error interno del servidor.", "code": "db_error"}), 500

    except Exception as e:
        print(f"Error inesperado al listar applicants: {e}")
        return jsonify({"detail": "Error interno inesperado.", "code": "internal_error"}), 500


# Ruta para actualizar el estado de postulación de un subcontratista
@opportunities_bp.patch("/<id_opportunities>/applicants/<subcon_id>")
def update_applicant_state(id_opportunities, subcon_id):
    try:
        data = request.get_json()
        state = data.get("state") if data else None

        with get_session() as session:
            link = session.get(OpportSubcLink, (id_opportunities, subcon_id))
            if not link:
                return jsonify({"error": "Applicant not found"}), 404

            link.State = state
            session.add(link)
            session.commit()

            return jsonify({
                "opport_id": id_opportunities,
                "subcon_id": subcon_id,
                "state": state,
            }), 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al actualizar estado: {db_error}")
        return jsonify({"detail": "Error interno del servidor.", "code": "db_error"}), 500

    except Exception as e:
        print(f"Error inesperado al actualizar estado: {e}")
        return jsonify({"detail": "Error interno inesperado.", "code": "internal_error"}), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una opportunity
@opportunities_bp.post("/")
def create_opportunity():
    try:
        data = request.get_json()
        create_opportunity = OpportunitiesCreate.model_validate(data)
        obj = Opportunities.model_validate(create_opportunity)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Opportunities, "ID_Opportunities", "OPP")
            obj.ID_Opportunities = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:
        session.rollback()
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe una opportunity con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        session.rollback()
        print(f"Error de base de datos al crear opportunity: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de opportunity: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar una opportunity
@opportunities_bp.patch("/<id_opportunities>")
def update_opportunity(id_opportunities):
    session = None
    try:
        # force=True ignores Content-Type header so JSON is always parsed
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400

        with get_session() as session:
            obj = session.get(Opportunities, id_opportunities)
            if not obj:
                return jsonify({"error": "Opportunity not found"}), 404

            # Update plain string fields directly — no Pydantic coercion needed
            for field in ("Project_name", "Description", "Priority", "ID_Jobs", "ID_Order"):
                if field in data:
                    v = data[field]
                    setattr(obj, field, str(v).strip() if v is not None else None)

            # Boolean State
            if "State" in data:
                v = data["State"]
                obj.State = bool(v) if v is not None else None

            # Datetime Start_Date — accept both "YYYY-MM-DD" and "YYYY-MM-DDTHH:MM:SS"
            if "Start_Date" in data:
                sd = data["Start_Date"]
                if sd is None:
                    obj.Start_Date = None
                else:
                    try:
                        s = str(sd)[:19]
                        obj.Start_Date = (
                            datetime.fromisoformat(s) if "T" in s
                            else datetime.strptime(s[:10], "%Y-%m-%d")
                        )
                    except (ValueError, TypeError):
                        pass  # leave existing value untouched

            save_with_retry(session, obj)

            # Return a plain dict to avoid SQLModel/Pydantic serialization quirks
            return jsonify({
                "ID_Opportunities": obj.ID_Opportunities,
                "Project_name": obj.Project_name,
                "Description": obj.Description,
                "State": obj.State,
                "Priority": obj.Priority,
                "Start_Date": obj.Start_Date.isoformat() if obj.Start_Date else None,
                "ID_Jobs": obj.ID_Jobs,
                "ID_Order": obj.ID_Order,
            }), 200

    except IntegrityError as e:
        if session:
            session.rollback()
        print(f"Error de integridad (PATCH opportunity): {e}")
        return jsonify({"detail": "Error de integridad al actualizar la opportunity."}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar opportunity: {db_error}")
        return jsonify({"detail": "Error interno del servidor.", "code": "db_error"}), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al actualizar opportunity: {e}")
        return jsonify({"detail": f"Error inesperado: {str(e)}", "code": "internal_error"}), 500


# Ruta para eliminar una opportunity
@opportunities_bp.delete("/<id_opportunities>")
def delete_opportunity(id_opportunities):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Opportunities, id_opportunities)
            if not obj:
                return jsonify({"error": "Opportunity not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted Opportunity {id_opportunities}"}), 200

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar la opportunity porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar opportunity: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al eliminar opportunity: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
