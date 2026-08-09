import re

from src.utils.middleware.exceptions_handler import AppException

# REG-147: job_code se interpola en queries QBO (el SQL-like de Intuit no
# soporta parámetros). Whitelist estricta antes de interpolar.
_JOB_CODE_RE = re.compile(r"^[A-Z]{2,4}\d+$")


def validate_job_code(job_code: str) -> str:
    code = (job_code or "").strip().upper()
    if not _JOB_CODE_RE.match(code):
        raise AppException(
            f"job_code inválido: {job_code!r} (formato esperado: QID1234)",
            "invalid_job_code", 400)
    return code
