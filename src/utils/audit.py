# src/utils/audit.py
"""
Sistema de auditoría para el timeline de Jobs.

Uso básico en una ruta:
    @job_bp.patch("/<id_job>")
    @handle_exceptions()
    @audit(action="Job updated", id_param="id_job")
    def update_job(id_job): ...

Para rutas donde ID_Jobs viene del body (no del URL):
    @audit(action="Change Order created", job_id_from="body")
    def create_change_order(): ...

Para el webhook de Podio, llamar directamente:
    from src.utils.audit import log_activity
    log_activity(session, action="Job synced from Podio",
                 job_id=job.ID_Jobs, source="podio")
"""
from __future__ import annotations

import functools
from datetime import datetime
from typing import Callable

from flask import request as flask_request

from .id_generator import generate_custom_id


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOURCE_APP = "App"
SOURCE_PODIO = "Podio"

# ---------------------------------------------------------------------------
# Core writer
# ---------------------------------------------------------------------------


def log_activity(
    session,
    *,
    action: str,
    entity_id: str | None = None,
    entity_type: str = "Job",  # "Job", "Member", "Subcontractor", "Technician"
    job_id: str | None = None,
    member_id: str | None = None,  # Quién ejecuta la acción
    description: str | None = None,
    source: str = SOURCE_APP,
) -> None:
    # Import aquí para evitar circular imports
    from ..models.TLActivityModel import TLActivity

    try:
        new_id = generate_custom_id(
            session, TLActivity, "ID_TLActivity", "TLA")

        # Diccionario de mapeo
        entity_map = {
            "Job": "ID_Jobs",
            "Member": "ID_Member",
            "Subcontractor": "ID_Subcontractor",
            "Technician": "ID_Technician",
            "ParentMgmtCo": "ID_Community_Tracking",
            "Client": "ID_Client",
            "Tasks": "ID_Tasks",
            "Order": "ID_Order",
            "EstimateCost": "ID_EstimateCost",
            "ChangeOrder": "ID_ChangeOrder"
        }

        # Preparamos los datos base
        activity_data = {
            "ID_TLActivity": new_id,
            "Action": action,
            "Action_datetime": datetime.now(),
            "Description": _build_description(description, source),
            "ID_Member": member_id,  # El autor (siempre va en ID_Member)
        }

        # Asignar el ID de la entidad a su columna correspondiente
        target_field = entity_map.get(entity_type)
        if target_field and entity_id:
            activity_data[target_field] = entity_id

        # Si recibimos un job_id y la entidad NO es un Job (para no duplicar),
        # lo asignamos a la columna ID_Jobs.
        if job_id and entity_type != "Job":
            activity_data["ID_Jobs"] = job_id

        entry = TLActivity(**activity_data)
        session.add(entry)

    except Exception as e:
        # Nunca dejamos que el log rompa la operación principal
        print(f"⚠️  [audit] log_activity failed silently: {e}")


# ---------------------------------------------------------------------------
# Description helpers
# ---------------------------------------------------------------------------

def _build_description(description: str | None, source: str) -> str | None:
    parts = []
    if source == SOURCE_PODIO:
        parts.append("Source: Podio")
    if description:
        parts.append(description)
    return "  |  ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Internal DB write helper
# ---------------------------------------------------------------------------

def _write_audit(
    action: str,
    entity_id: str | None,
    entity_type: str,
    member_id: str | None,
    method: str,
    body: dict,
    track_fields: bool,
    job_id=None
) -> None:
    """
    Abre su propia sesión y persiste la entrada de auditoría.
    Silencia cualquier excepción para no interrumpir la operación principal.
    """
    try:
        from ..database.db_sqlmodel import get_session
        description = _build_action_description(
            method=method,
            action=action,
            body=body,
            track_fields=track_fields,
        )
        with get_session() as session:
            log_activity(
                session,
                action=action,
                entity_id=entity_id,
                entity_type=entity_type,
                job_id=job_id,
                member_id=member_id,
                description=description,
                source=SOURCE_APP,
            )
            session.commit()
    except Exception as e:
        print(f"⚠️  [audit] decorator DB write failed: {e}")


# ---------------------------------------------------------------------------
# @audit decorator
# ---------------------------------------------------------------------------

def audit(
    action: str,
    *,
    entity_type: str = "Job",      # "Job", "Client", etc.
    id_param: str = "id_job",      # El nombre en el URL de Flask
    id_from: str = "url",          # "url" | "body" | "response"
    job_id_from: str | None = None,
    track_fields: bool = True,
) -> Callable:

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            method = flask_request.method.upper()
            body: dict = flask_request.get_json(silent=True) or {}
            member_id = flask_request.headers.get("X-User-Id") or None

            # Mapeo automático de qué ID buscar en el JSON (ID_Jobs, ID_Client, etc.)
            if entity_type == "Job":
                json_field = "ID_Jobs"
            elif entity_type == "ParentMgmtCo":
                json_field = "ID_Community_Tracking"
            else:
                json_field = f"ID_{entity_type}"

            def get_eid(resp=None):
                if id_from == "url":
                    return kwargs.get(id_param)
                source_data = body if id_from == "body" else (resp or {})
                return source_data.get(json_field) or source_data.get(json_field.lower())

            # --- 2. Lógica para el ID del Job (Si aplica) ---
            def get_job_id(resp=None):
                if not job_id_from:
                    return None
                if job_id_from == "url":
                    # Por defecto busca "id_job" en la URL si vas a un sub-recurso
                    return kwargs.get("id_job") or kwargs.get(id_param)
                source = body if job_id_from == "body" else (resp or {})
                return source.get("ID_Jobs") or source.get("id_jobs")

            # ── PRE-LOG: DELETE ──────────────────────────────────────────
            # El job aún existe en la BD → la FK se satisface correctamente.
            # PRE-LOG: DELETE
            if method == "DELETE":
                eid = get_eid()
                jid = get_job_id()
                _write_audit(action, eid, entity_type, member_id,
                             method, body, track_fields, job_id=jid)

            # ── Ejecutar la función original ─────────────────────────────
            result = fn(*args, **kwargs)

            # ── POST-LOG: todo lo que NO sea DELETE ──────────────────────
            if method != "DELETE":
                response_obj, status_code = _unpack_result(result)
                if 200 <= status_code < 300:
                    eid = get_eid(response_obj)
                    jid = get_job_id(response_obj)
                    _write_audit(action, eid, entity_type, member_id,
                                 method, body, track_fields, job_id=jid)

            return result
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unpack_result(result) -> tuple[dict, int]:
    """
    Desempaqueta respuestas de Flask (tuplas, dicts o Response objetos).
    """
    # Caso 1: Es una tupla (objeto, status_code) -> return jsonify(), 200
    if isinstance(result, tuple) and len(result) >= 2:
        body, code = result[0], result[1]

        # Si el cuerpo es un objeto Response (jsonify)
        if hasattr(body, "get_json"):
            try:
                data = body.get_json(silent=True) or {}
                return data, int(code)
            except Exception:
                return {}, int(code)

        # Si el cuerpo ya es un dict
        if isinstance(body, dict):
            return body, int(code)

        return {}, int(code)

    # Caso 2: Es un objeto Response directo -> return jsonify()
    if hasattr(result, "status_code"):
        try:
            # .get_json(silent=True) es más seguro que force=True en algunos contextos
            data = result.get_json(silent=True) or {}
            return data, result.status_code
        except Exception:
            return {}, result.status_code

    # Caso 3: Es un dict directo -> return {"msj": "ok"}
    if isinstance(result, dict):
        return result, 200

    return {}, 200


def _build_action_description(
    *,
    method: str,
    action: str,
    body: dict,
    track_fields: bool,
) -> str | None:
    parts = []

    if method == "PATCH" and track_fields and body:
        fields = list(body.keys())
        if fields:
            parts.append(f"Fields: {', '.join(fields)}")

        # Detectar cambio de status específicamente
        for key, value in body.items():
            if "status" in key.lower():
                parts.append(f"New {key}: {value}")

    return "  |  ".join(parts) if parts else None
