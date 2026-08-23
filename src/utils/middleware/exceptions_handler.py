from functools import wraps
from flask import jsonify, request
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import Session
import inspect
from .logs.logs import logger


# Clase que permite lanzar errores sin que sean 500
class AppException(Exception):
    def __init__(self, detail: str, code: str, status_code: int = 400):
        self.detail = detail
        self.code = code
        self.status_code = status_code
        super().__init__(detail)


# Función para detectar si hay session para hacer rollback
def rollback_if_possible():
    """
    Busca un objeto Session activo en los argumentos de la función
    y ejecuta rollback si lo encuentra.
    """
    frame = inspect.currentframe().f_back

    while frame:
        for value in frame.f_locals.values():
            if isinstance(value, Session):
                try:
                    value.rollback()
                    return
                except Exception:
                    return
        frame = frame.f_back


# Decorador de errores
def handle_exceptions():
    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            try:
                return func(*args, **kwargs)

            # -----------------------------------
            # APP CONTROLLED ERROR
            # -----------------------------------
            except AppException as ae:
                logger.info(
                    f"APP ERROR | {request.method} {request.path} | "
                    f"{ae.code} | {ae.detail}"
                )

                return jsonify({
                    "detail": ae.detail,
                    "code": ae.code
                }), ae.status_code

            # -----------------------------------
            # VALIDATION ERROR (400)
            # -----------------------------------
            except ValidationError as ve:
                logger.warning(
                    f"VALIDATION ERROR | {request.method} {request.path} | "
                    f"{ve.errors()}",
                    exc_info=True
                )

                # `ctx` incluye la excepción original, que NO es serializable:
                # cualquier ValidationError nacido de un `raise ValueError` en un
                # validador reventaba aquí y Flask devolvía un 500 SIN mensaje en
                # vez del 400 con el detalle. Antes no se notaba porque solo
                # había errores de tipo, cuyo ctx sí es serializable.
                return jsonify({
                    "detail": "Error de validación en los datos enviados.",
                    "code": "validation_error",
                    "errors": ve.errors(include_context=False, include_url=False)
                }), 400

            # -----------------------------------
            # INTEGRITY ERROR (409)
            # -----------------------------------
            except IntegrityError as ie:
                rollback_if_possible()

                error_message = str(ie.orig).lower()

                if "unique" in error_message:
                    detail = "Registro duplicado."
                    code = "duplicate_entry"
                elif "foreign key" in error_message:
                    detail = "Referencia inválida."
                    code = "foreign_key_violation"
                elif "not null" in error_message:
                    detail = "Campo obligatorio faltante."
                    code = "not_null_violation"
                else:
                    detail = "Conflicto de integridad en base de datos."
                    code = "integrity_error"

                logger.warning(
                    f"INTEGRITY ERROR | {request.method} {request.path} | "
                    f"{error_message}",
                    exc_info=True
                )

                return jsonify({
                    "detail": detail,
                    "code": code
                }), 409

            # -----------------------------------
            # SQLALCHEMY ERROR (500)
            # -----------------------------------
            except SQLAlchemyError as db_error:
                rollback_if_possible()

                logger.error(
                    f"DB ERROR | {request.method} {request.path} | "
                    f"{str(db_error)}",
                    exc_info=True
                )

                return jsonify({
                    "detail": "Error interno de base de datos.",
                    "code": "db_error"
                }), 500

            # -----------------------------------
            # ERROR GENERAL (500)
            # -----------------------------------
            except Exception as e:
                rollback_if_possible()

                logger.critical(
                    f"UNEXPECTED ERROR | {request.method} {request.path} | "
                    f"{str(e)}",
                    exc_info=True
                )

                return jsonify({
                    "detail": "Error interno inesperado del servidor.",
                    "code": "internal_error"
                }), 500

        return wrapper
    return decorator
