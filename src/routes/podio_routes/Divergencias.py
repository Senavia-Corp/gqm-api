"""Informe de divergencias campo a campo entre la app y Podio.

## Por qué existe

Es el contrapeso de la regla del vacío. El cliente decidió que **un campo vacío
en Podio es ausencia de dato y no se escribe nunca**, lo cual es correcto — pero
tiene un precio: si alguien vacía un campo porque el valor era erróneo, la app
conserva el viejo y los dos lados quedan separados sin que nadie se entere.

Ese precio es razonable siempre que la divergencia sea **visible**. Hasta ahora
no lo era: la reconciliación que existe (`Paridad.py`) compara siete columnas de
dinero del job y no baja al nivel de línea, así que no ve un alquiler, un BD fee
ni una cuota descuadrados.

Este informe sí baja. **Sólo lectura**: no escribe ni en Podio ni en la base.

    GET /admin/podio/divergencias?type=QID&year=2026&limit=50
    GET /admin/podio/divergencias/<ID_Jobs>
"""
from flask import Blueprint, jsonify, request
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.OrderModel import Order
from src.models.OrderPaymentModel import OrderPayment
from src.podio.services.job_services import podio_jobs_router
from src.utils import podio_slots
from src.utils.mappers.from_podio import payment_slots
from src.utils.middleware.exceptions_handler import AppException, handle_exceptions
from src.utils.middleware.logs.logs import logger

divergencias_bp = Blueprint("divergencias", __name__, url_prefix="/admin/podio")

TOLERANCIA = 0.01


def _valor_podio(item, ext_id):
    from src.podio.webhook.jobs_hook_sync import _valor_money_del_item

    return _valor_money_del_item(item, ext_id)


def _difiere(app, podio) -> bool:
    if app is None and podio is None:
        return False
    if app is None or podio is None:
        return True
    return abs(float(app) - float(podio)) >= TOLERANCIA


def _divergencias_de_huecos(session, job, item) -> list:
    """Alquileres, BD fees y compras: cada registro contra SU hueco."""
    fuera = []
    for clave in ("QID.bldg_dept_fees", "QID.purchases_list"):
        fam = podio_slots.familia(clave)
        for registro in podio_slots.registros(session, fam, job.ID_Jobs):
            hueco = getattr(registro, "podio_field", None)
            if not hueco:
                fuera.append({"concepto": fam.clave, "campo": None,
                              "registro": podio_slots._pk(registro),
                              "motivo": "no declara hueco en Podio"})
                continue
            presente, en_podio = _valor_podio(item, hueco)
            en_app = podio_slots._importe(fam, registro)
            if not presente:
                fuera.append({"concepto": fam.clave, "campo": hueco,
                              "registro": podio_slots._pk(registro),
                              "app": en_app, "podio": None,
                              "motivo": "el campo no existe en esa app-año"})
            elif _difiere(en_app, en_podio):
                fuera.append({"concepto": fam.clave, "campo": hueco,
                              "registro": podio_slots._pk(registro),
                              "app": en_app, "podio": en_podio,
                              "motivo": "importes distintos"})
    return fuera


def _divergencias_de_cuotas(session, job, item) -> list:
    """Cuotas al técnico: cada cuota contra su hueco de pago."""
    if not payment_slots.habilitado(job.Job_type):
        return []

    fuera = []
    ordenes = session.exec(select(Order).where(
        Order.job_podio_id == job.podio_item_id)).all()
    for orden in ordenes:
        for cuota in session.exec(select(OrderPayment).where(
                OrderPayment.ID_Order == orden.ID_Order)).all():
            hueco = cuota.podio_field
            if not hueco:
                continue
            presente, en_podio = _valor_podio(item, hueco)
            if presente and _difiere(cuota.Amount, en_podio):
                fuera.append({"concepto": "cuota", "campo": hueco,
                              "registro": cuota.ID_OrderPayment,
                              "orden": orden.ID_Order, "cuota": cuota.Installment,
                              "app": cuota.Amount, "podio": en_podio,
                              "motivo": "importes distintos"})
    return fuera


# Los agregados son DERIVADOS: la app manda y los devuelve a Podio (G3). Si
# aquí aparece uno, es que esa devolución falló y hay que mirarlo.
AGREGADOS = {
    "QID": [("Gqm_target_sold_pricing", "gqm-target-sold-price"),
            ("Estimated_rent", "estimated-hoa-admin-total"),
            ("Estimated_material", "estimated-material-total"),
            ("Estimated_city", "fees-and-cost")],
    "PTL": [("Gqm_target_sold_pricing", "money"), ("Ptl_gc_fee", "money-2")],
    "PAR": [("Gqm_target_sold_pricing", "gqm-target-sold-price")],
}


def _divergencias_de_agregados(job, item) -> list:
    fuera = []
    for columna, ext in AGREGADOS.get(job.Job_type, []):
        presente, en_podio = _valor_podio(item, ext)
        if not presente:
            continue
        en_app = getattr(job, columna, None)
        if _difiere(en_app, en_podio):
            fuera.append({"concepto": "agregado", "campo": ext, "columna": columna,
                          "app": en_app, "podio": en_podio,
                          "motivo": "el recálculo no llegó a Podio"})
    return fuera


def _revisar(session, job) -> dict:
    anio = job.podio_app_year
    if not anio or not job.podio_item_id:
        return {"job": job.ID_Jobs, "saltado": "sin ítem o sin año de app"}

    servicio = podio_jobs_router.get_readonly_service(job.Job_type, anio)
    item = servicio.get_item(int(job.podio_item_id))

    hallazgos = _divergencias_de_agregados(job, item) + \
        _divergencias_de_cuotas(session, job, item)
    if job.Job_type == "QID":
        hallazgos += _divergencias_de_huecos(session, job, item)

    return {"job": job.ID_Jobs, "tipo": job.Job_type, "anio": anio,
            "podio_item_id": job.podio_item_id, "divergencias": hallazgos}


@divergencias_bp.get("/divergencias")
@handle_exceptions()
def listar_divergencias():
    tipo = (request.args.get("type") or "").upper()
    anio = request.args.get("year", type=int)
    limite = request.args.get("limit", default=25, type=int)

    if tipo and tipo not in ("QID", "PTL", "PAR"):
        raise AppException(f"Tipo de job inválido: {tipo}", "invalid_job_type", 400)

    with get_session() as session:
        q = select(Job).where(Job.podio_item_id.is_not(None))
        if tipo:
            q = q.where(Job.Job_type == tipo)
        if anio:
            q = q.where(Job.podio_app_year == anio)

        informes, con_divergencia = [], 0
        for job in session.exec(q.limit(limite)).all():
            try:
                inf = _revisar(session, job)
            except Exception as e:
                logger.warning("No se pudo revisar %s: %s", job.ID_Jobs, e)
                inf = {"job": job.ID_Jobs, "error": str(e)}
            if inf.get("divergencias"):
                con_divergencia += 1
            informes.append(inf)

        return jsonify({
            "revisados": len(informes),
            "con_divergencia": con_divergencia,
            "jobs": [i for i in informes if i.get("divergencias") or i.get("error")],
        }), 200


@divergencias_bp.get("/divergencias/<id_job>")
@handle_exceptions()
def divergencias_de_un_job(id_job):
    with get_session() as session:
        job = session.get(Job, id_job)
        if not job:
            raise AppException("Job no encontrado", "job_not_found", 404)
        return jsonify(_revisar(session, job)), 200
