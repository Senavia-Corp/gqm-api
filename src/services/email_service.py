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


_NOMBRE_DE_CUENTA = {
    "member": "GQM team member",
    "technician": "technician",
    "subcontractor": "subcontractor",
}


def send_password_reset(to: str, enlaces) -> bool:
    """UN correo con todos los enlaces de reinicio de ese buzon.

    `enlaces` es una lista de `(tipo_de_cuenta, url)`. Se acepta tambien una
    URL suelta por compatibilidad con los llamadores antiguos.

    Un correo y no uno por cuenta (O-05 bis): mandar N costaba N conexiones
    SMTP sincronas y hacia que el tiempo de respuesta delatara CUANTAS cuentas
    tiene esa direccion — el «siempre 200» no oculta nada al reloj.

    El tipo de cuenta va junto a cada enlace porque, con dos enlaces iguales,
    el destinatario no sabria cual reinicia cual.

    Nota honesta: quien controle el buzon puede reiniciar TODAS las cuentas
    abiertas sobre el. Eso es inherente a recuperar la contrasena por correo;
    que antes solo alcanzara a la primera por orden de tabla era un accidente,
    no un control de seguridad.
    """
    if isinstance(enlaces, str):
        enlaces = [(None, enlaces)]
    enlaces = list(enlaces)
    if not enlaces:
        return False

    varias = len(enlaces) > 1
    asunto = ("Reset your GQM passwords" if varias else "Reset your GQM password")

    filas_html, filas_texto = [], []
    for tipo, url in enlaces:
        nombre = _NOMBRE_DE_CUENTA.get(tipo or "", "")
        etiqueta = f"Reset {nombre} password" if nombre else "Reset password"
        filas_html.append(f"""
          <p style="margin:14px 0">
            <a href="{url}" style="background:#14532d;color:#fff;
               padding:10px 18px;border-radius:6px;text-decoration:none">
               {etiqueta}</a></p>""")
        filas_texto.append(f"{etiqueta}: {url}")

    encabezado = (
        "<p>This email address has more than one GQM account. "
        "Use the link for the one you want to reset.</p>"
        if varias else
        "<p>We received a request to reset your password.</p>")

    return send_email(
        to, asunto,
        _layout("Password reset", encabezado + "".join(filas_html) + """
          <p>The link expires in 30 minutes. If you didn't request this,
             you can ignore this email.</p>"""),
        text="\n".join(filas_texto) + "\n(expires in 30 minutes)",
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
