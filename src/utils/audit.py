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

SOURCE_APP = "app"
SOURCE_PODIO = "podio"

STATUS_FIELD = "Job_status"


# ---------------------------------------------------------------------------
# Core writer
# ---------------------------------------------------------------------------

def log_activity(
    session,
    *,
    action: str,
    job_id: str | None = None,
    member_id: str | None = None,
    description: str | None = None,
    source: str = SOURCE_APP,
) -> None:
    """
    Escribe una entrada en tlactivity dentro de la sesión dada.
    No hace commit — el caller es responsable del commit.

    Args:
        session:     SQLModel/SQLAlchemy session ya abierta.
        action:      Texto corto de la acción. Ej: "Job updated".
        job_id:      ID_Jobs relacionado (puede ser None).
        member_id:   ID_Member que ejecutó la acción (None = desconocido / Podio).
        description: Detalle adicional. Ej: "Fields changed: Job_status, Date_assigned".
        source:      "app" | "podio"
    """
    # Import aquí para evitar circular imports
    from ..models.TLActivityModel import TLActivity

    try:
        new_id = generate_custom_id(
            session, TLActivity, "ID_TLActivity", "TLA")

        entry = TLActivity(
            ID_TLActivity=new_id,
            Action=action,
            Action_datetime=datetime.now(),
            Description=_build_description(description, source),
            ID_Jobs=job_id,
            ID_Member=member_id,
        )
        session.add(entry)
        # No hacemos commit aquí — el caller lo maneja
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


def _changed_fields(before: dict, after: dict) -> list[str]:
    """Returns list of field names whose value changed."""
    changed = []
    for key, new_val in after.items():
        if key in before and before[key] != new_val:
            changed.append(key)
    return changed


def _status_changed(before: dict, after: dict) -> tuple[bool, str | None, str | None]:
    """Returns (changed, old_status, new_status)."""
    old = before.get(STATUS_FIELD)
    new = after.get(STATUS_FIELD)
    if new is not None and old != new:
        return True, old, new
    return False, None, None


# ---------------------------------------------------------------------------
# Internal DB write helper
# ---------------------------------------------------------------------------

def _write_audit(
    action: str,
    job_id: str | None,
    member_id: str | None,
    method: str,
    body: dict,
    track_fields: bool,
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
    id_param: str = "id_job",
    job_id_from: str = "url",   # "url" | "body" | "response"
    track_fields: bool = True,
) -> Callable:
    """
    Decorador que registra automáticamente una entrada en tlactivity.

    - Para DELETE: registra ANTES de ejecutar la función, mientras el job
      todavía existe en la BD (evita ForeignKeyViolation).
    - Para el resto (POST, PATCH, etc.): registra DESPUÉS de ejecutar,
      solo si la respuesta fue exitosa (2xx).

    Extrae automáticamente:
      - ID_Jobs del parámetro URL (id_param), del body, o de la respuesta JSON
      - ID_Member del header X-User-Id (puesto por el frontend)
      - Campos cambiados (solo en PATCH, si track_fields=True)
      - Cambio de Job_status como descripción especial

    Usage:
        @job_bp.post("/")
        @handle_exceptions()
        @audit("Job created")
        def create_job(): ...

        @job_bp.patch("/<id_job>")
        @handle_exceptions()
        @audit("Job updated", id_param="id_job")
        def update_job(id_job): ...

        @job_bp.delete("/<id_job>")
        @handle_exceptions()
        @audit("Job deleted", id_param="id_job")
        def delete_job(id_job): ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            method = flask_request.method.upper()
            body: dict = flask_request.get_json(silent=True) or {}
            member_id = flask_request.headers.get("X-User-Id") or None

            # ── PRE-LOG: DELETE ──────────────────────────────────────────
            # El job aún existe en la BD → la FK se satisface correctamente.
            if method == "DELETE":
                job_id = _extract_job_id(
                    job_id_from=job_id_from,
                    id_param=id_param,
                    kwargs=kwargs,
                    body=body,
                    response={},
                )
                _write_audit(action, job_id, member_id,
                             method, body, track_fields)

            # ── Ejecutar la función original ─────────────────────────────
            result = fn(*args, **kwargs)

            # ── POST-LOG: todo lo que NO sea DELETE ──────────────────────
            if method != "DELETE":
                response_obj, status_code = _unpack_result(result)

                # Solo loguear si fue exitoso
                if _is_success(status_code):
                    job_id = _extract_job_id(
                        job_id_from=job_id_from,
                        id_param=id_param,
                        kwargs=kwargs,
                        body=body,
                        response=response_obj,
                    )
                    _write_audit(action, job_id, member_id,
                                 method, body, track_fields)

            return result

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unpack_result(result) -> tuple[dict, int]:
    """
    Flask routes can return:
      - (dict, int)
      - (Response, int)
      - Response
    Returns (parsed_dict_or_none, status_code).
    """
    if isinstance(result, tuple):
        body, code = result[0], result[1]
        if hasattr(body, "get_json"):
            try:
                return body.get_json(force=True) or {}, int(code)
            except Exception:
                return {}, int(code)
        if isinstance(body, dict):
            return body, int(code)
        return {}, int(code)

    # Single Response object
    if hasattr(result, "status_code"):
        try:
            return result.get_json(force=True) or {}, result.status_code
        except Exception:
            return {}, result.status_code

    return {}, 200


def _is_success(status_code: int) -> bool:
    return 200 <= status_code < 300


def _extract_job_id(
    *,
    job_id_from: str,
    id_param: str,
    kwargs: dict,
    body: dict,
    response: dict,
) -> str | None:
    if job_id_from == "url":
        return kwargs.get(id_param)

    if job_id_from == "body":
        return body.get("ID_Jobs") or body.get("id_jobs")

    if job_id_from == "response":
        return response.get("ID_Jobs") or response.get("id_jobs")

    return None


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
        if STATUS_FIELD in body:
            parts.append(f"New status: {body[STATUS_FIELD]}")

    return "  |  ".join(parts) if parts else None
