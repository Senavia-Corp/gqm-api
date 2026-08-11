"""Censo Podio ↔ BD. Solo lectura: no escribe ni en Podio ni en la BD.

La entrega se firma cuando el cliente abre una app de Podio, lee su contador de
items, abre el panel y ve el mismo número. Esto es lo que mide esa distancia.

Dos medidas independientes del lado de Podio y **tienen que coincidir**:

- la **sonda**: `limit=1` y se lee `filtered`, que es el contador que la UI de
  Podio enseña;
- la **enumeración**: paginar la app entera y contar ids únicos.

Si difieren, alguien tocó la app a mitad del recuento. No se promedia: se
reintenta la app entera. Y sin enumeración completa no se puede afirmar que a un
job le falta su item — de una página parcial no se infiere ausencia.

Trampa de desarrollo (C4): con `APP_ENV=test` los cuatro años comparten las
credenciales TAP, así que las 4 app-años de un tipo son **la misma app de
Podio**. Comparar por año ahí da un delta falso 3 de cada 4 veces. Por eso la
respuesta lleva `app_id`, `apps_colapsadas` y `comparable_por_anio`: en dev la
comparación válida es contra `bd.por_app_id`.
"""
from flask import Blueprint, jsonify, request
from sqlmodel import func, select

from src.config import JOB_TYPES, JOB_YEARS, PODIO_JOB_APPS
from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.podio.services.job_services import podio_jobs_router
from src.utils.job_app_year import expr_anio_app
from src.utils.middleware.exceptions_handler import handle_exceptions

paridad_bp = Blueprint("paridad", __name__, url_prefix="/admin/podio")

TOPE_PAGINA = 500  # verificado contra Podio: 501 devuelve 400


def _app_id_de(job_type: str, year: int):
    return str((PODIO_JOB_APPS.get(year, {}).get(job_type) or {}).get("APP_ID") or "")


def _anios_de_la_misma_app(job_type: str, app_id: str) -> list[int]:
    """Los años cuyas credenciales apuntan al mismo app_id.

    En producción devuelve un solo año. En `APP_ENV=test` devuelve los cuatro,
    porque las TAP se reutilizan para todos.
    """
    return sorted(a for a in JOB_YEARS if _app_id_de(job_type, a) == str(app_id))


def _enumerar(servicio, total_esperado: int) -> dict:
    """Pagina la app entera. Devuelve los ids y las claves formateadas."""
    items, offset = {}, 0
    while True:
        pagina = servicio.get_items_page(limit=TOPE_PAGINA, offset=offset)
        lote = pagina.get("items") or []
        if not lote:
            break
        for item in lote:
            items[str(item.get("item_id"))] = item.get("app_item_id_formatted")
        offset += len(lote)
        if len(items) >= (total_esperado or 0) and total_esperado:
            break
        if len(lote) < TOPE_PAGINA:
            break
    return items


def _conteo_bd(session, job_type: str, anios: list[int]) -> int:
    return session.exec(
        select(func.count()).select_from(Job).where(
            Job.Job_type == job_type, expr_anio_app().in_(anios))
    ).one()


def _paridad_de_app(session, job_type: str, year: int, enumerar: bool) -> dict:
    servicio = podio_jobs_router.get_readonly_service(job_type, year)
    app_id = str(servicio.app_id)
    colapsados = _anios_de_la_misma_app(job_type, app_id)
    comparable = len(colapsados) <= 1

    sonda = servicio.get_items_page(limit=1, offset=0)
    total_podio = sonda.get("filtered")
    if total_podio is None:
        total_podio = sonda.get("total")

    resultado = {
        "tipo": job_type,
        "anio": year,
        "podio": {"app_id": app_id, "filtered": sonda.get("filtered"),
                  "total": sonda.get("total"), "enumerados": None},
        "bd": {
            "por_anio": _conteo_bd(session, job_type, [year]),
            "por_app_id": _conteo_bd(session, job_type, colapsados),
        },
        "apps_colapsadas": colapsados if not comparable else [],
        "comparable_por_anio": comparable,
    }

    # El lado de la BD con el que se compara depende de si la app está partida
    # por año de verdad o no. Comparar contra `por_anio` en dev es comparar la
    # misma app de Podio contra un cuarto de la BD.
    referencia_bd = resultado["bd"]["por_anio" if comparable else "por_app_id"]
    resultado["delta"] = (total_podio or 0) - referencia_bd

    if not comparable:
        resultado["nota"] = (
            f"APP_ENV=test: los años {colapsados} comparten el app_id {app_id}. "
            f"La comparación válida aquí es podio.total contra bd.por_app_id; "
            f"la paridad por año solo puede demostrarse contra credenciales reales."
        )

    if enumerar:
        encontrados = _enumerar(servicio, total_podio)
        resultado["podio"]["enumerados"] = len(encontrados)

        if len(encontrados) != (total_podio or 0):
            # No se promedia: la app se movió mientras se contaba.
            resultado["ok"] = False
            resultado["inconsistente"] = (
                f"la sonda dice {total_podio} y la enumeración {len(encontrados)}; "
                f"alguien tocó la app a mitad del recuento. Reintentar la app entera."
            )
            return resultado

        anios_bd = colapsados if not comparable else [year]
        filas = session.exec(
            select(Job.ID_Jobs, Job.podio_item_id).where(
                Job.Job_type == job_type, expr_anio_app().in_(anios_bd))
        ).all()
        en_bd = {str(p): i for i, p in filas if p}

        resultado["faltan"] = [
            {"item_id": iid, "app_item_id_formatted": clave}
            for iid, clave in encontrados.items() if iid not in en_bd
        ]
        resultado["sobran"] = [
            {"item_id": iid, "ID_Jobs": id_jobs}
            for iid, id_jobs in en_bd.items() if iid not in encontrados
        ]
        # La prueba de que la secuencia nativa se preservó: la clave de Podio y
        # el ID del job tienen que ser el mismo string en todo par emparejado.
        resultado["desalineados"] = [
            {"item_id": iid, "ID_Jobs": en_bd[iid], "app_item_id_formatted": clave}
            for iid, clave in encontrados.items()
            if iid in en_bd and clave and str(clave) != str(en_bd[iid])
        ]
        resultado["locales_sin_item"] = len([1 for i, p in filas if not p])

    resultado["ok"] = resultado.get("ok", True) and resultado["delta"] == 0
    return resultado


@paridad_bp.get("/parity")
@handle_exceptions()
def parity():
    """`?type=QID&year=2025`. Sin filtros recorre las 12 app-años.

    `?enumerar=true` pagina cada app entera y devuelve `faltan`/`sobran`; sin
    él solo se hace la sonda (una petición por app), que es lo que sirve para la
    pantalla del panel.
    """
    tipo = (request.args.get("type") or "").upper().strip() or None
    anio = request.args.get("year", type=int)
    enumerar = (request.args.get("enumerar") or "").lower() in ("1", "true", "yes")

    if tipo and tipo not in JOB_TYPES:
        return jsonify({"detail": f"type inválido: {tipo}. Válidos: {JOB_TYPES}"}), 400
    if anio and anio not in JOB_YEARS:
        return jsonify({"detail": f"year no configurado: {anio}. Válidos: {JOB_YEARS}"}), 400

    tipos = [tipo] if tipo else list(JOB_TYPES)
    anios = [anio] if anio else list(JOB_YEARS)

    filas, errores = [], []
    with get_session() as session:
        for t in tipos:
            for a in anios:
                try:
                    filas.append(_paridad_de_app(session, t, a, enumerar))
                except Exception as e:  # una app rota no puede tumbar el censo
                    errores.append({"tipo": t, "anio": a,
                                    "error": f"{type(e).__name__}: {e}"})

    return jsonify({
        "filas": filas,
        "errores": errores,
        "ok": bool(filas) and not errores and all(f.get("ok") for f in filas),
        "enumerado": enumerar,
    }), 200


@paridad_bp.get("/local_jobs")
@handle_exceptions()
def local_jobs():
    """Jobs sin `podio_item_id`: nunca llegaron a Podio.

    En producción son 7 (`QID-I60001..60005`, `PTL-I60001`, `PAR-I60001`). El
    borrado va en su propio endpoint y exige declarar cuántos dependientes se
    espera arrastrar.
    """
    with get_session() as session:
        filas = session.exec(
            select(Job.ID_Jobs, Job.Job_type, Job.Job_status, Job.Project_name)
            .where(Job.podio_item_id.is_(None))
            .order_by(Job.ID_Jobs)
        ).all()

    return jsonify({
        "total": len(filas),
        "jobs": [{"ID_Jobs": i, "Job_type": t, "Job_status": s, "Project_name": n}
                 for i, t, s, n in filas],
    }), 200
