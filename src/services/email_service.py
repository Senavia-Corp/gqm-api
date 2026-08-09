"""Servicio de correo (REG-049) — Gmail SMTP, decisión confirmada.

Envío síncrono con timeout corto; el fallo NUNCA rompe el flujo que lo
dispara (se loguea y se devuelve False). Notificaciones aprobadas: reset de
contraseña, bienvenida/alta, asignación a sub/técnico y nueva orden/CO.
(NO cambio de estado del job — decisión explícita.)
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from decouple import config

from src.utils.middleware.logs.logs import logger

_TIMEOUT = 15


def _smtp_settings():
    return {
        "host": config("SMTP_HOST", default=""),
        "port": config("SMTP_PORT", default=465, cast=int),
        "secure": config("SMTP_SECURE", default="true").lower() == "true",
        "user": config("SMTP_USER", default=""),
        "password": config("SMTP_PASS", default=""),
        "sender": config("MAIL_FROM", default=config("SMTP_USER", default="")),
    }


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    s = _smtp_settings()
    if not (s["host"] and s["user"] and s["password"] and to):
        logger.warning("SMTP no configurado o destinatario vacío: no se envía «%s»", subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = s["sender"]
    msg["To"] = to
    msg.attach(MIMEText(text or " ", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if s["secure"]:
            with smtplib.SMTP_SSL(s["host"], s["port"], timeout=_TIMEOUT) as server:
                server.login(s["user"], s["password"])
                server.sendmail(s["sender"], [to], msg.as_string())
        else:
            with smtplib.SMTP(s["host"], s["port"], timeout=_TIMEOUT) as server:
                server.starttls()
                server.login(s["user"], s["password"])
                server.sendmail(s["sender"], [to], msg.as_string())
        logger.info("📧 Enviado «%s» a %s", subject, to)
        return True
    except Exception:
        logger.exception("Fallo enviando «%s» a %s (no bloqueante)", subject, to)
        return False


def _layout(title: str, body_html: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px">
      <h2 style="color:#14532d;margin-bottom:4px">GQM Service Corp</h2>
      <h3 style="margin-top:0">{title}</h3>
      {body_html}
      <p style="color:#888;font-size:12px;margin-top:24px">
        Mensaje automático del panel GQM — no responder a este correo.</p>
    </div>"""


def send_password_reset(to: str, reset_url: str) -> bool:
    return send_email(
        to, "Reset your GQM password",
        _layout("Password reset", f"""
          <p>We received a request to reset your password.</p>
          <p><a href="{reset_url}" style="background:#14532d;color:#fff;
             padding:10px 18px;border-radius:6px;text-decoration:none">
             Reset password</a></p>
          <p>The link expires in 30 minutes. If you didn't request this,
             you can ignore this email.</p>"""),
        text=f"Reset your GQM password: {reset_url} (expires in 30 minutes)",
    )


def send_welcome(to: str, name: str) -> bool:
    return send_email(
        to, "Welcome to GQM",
        _layout("Welcome!", f"""
          <p>Hi {name},</p>
          <p>Your GQM panel account is ready. You can sign in with this
             email address.</p>"""),
        text=f"Hi {name}, your GQM panel account is ready.",
    )


def send_assignment_notification(to: str, name: str, job_id: str, job_name: str | None = None) -> bool:
    detail = f"{job_id}" + (f" — {job_name}" if job_name else "")
    return send_email(
        to, f"New assignment: {job_id}",
        _layout("New assignment", f"""
          <p>Hi {name},</p>
          <p>You have been assigned to job <strong>{detail}</strong>.</p>"""),
        text=f"Hi {name}, you have been assigned to job {detail}.",
    )


def send_new_order_or_co(to: str, name: str, kind: str, ref: str, job_id: str | None = None) -> bool:
    where = f" (job {job_id})" if job_id else ""
    return send_email(
        to, f"New {kind}: {ref}",
        _layout(f"New {kind}", f"""
          <p>Hi {name},</p>
          <p>A new {kind} <strong>{ref}</strong>{where} was created for you.</p>"""),
        text=f"Hi {name}, a new {kind} {ref}{where} was created for you.",
    )
