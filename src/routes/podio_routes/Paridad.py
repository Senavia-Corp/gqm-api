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
import hashlib
import time
from contextvars import ContextVar

from flask import Blueprint, jsonify, request
from sqlmodel import func, select

from src.config import JOB_TYPES, JOB_YEARS, PODIO_JOB_APPS
from src.database.db_sqlmodel import get_session
from src.models.ComDetailModel import CommissionDetail
from src.models.JobModel import Job
from src.podio.services.job_services import podio_jobs_router
from src.utils.borrado_job import (
    HuerfanosCreados,
    borrar_job_sin_huerfanos,
    inventario_dependientes,
    sentinela_huerfanos,
)
from src.utils.job_app_year import expr_anio_app
from src.utils.middleware.exceptions_handler import handle_exceptions

paridad_bp = Blueprint("paridad", __name__, url_prefix="/admin/podio")

TOPE_PAGINA = 500  # verificado contra Podio: 501 devuelve 400
PRESUPUESTO_S = 200      # el techo de función es 300 s; se deja margen
MARGEN_PAGINA_S = 8      # lo que puede tardar una página con reintentos

# Guardia de comisiones. `upsert_job_from_item` no llama a
# `process_job_to_commissions` — el disparo vive en las rutas de webhook y en el
# PATCH de jobs — así que importar ya no puede generar comisiones. Esto es la
# red por si alguien mete una llamada ahí dentro sin darse cuenta: un import
# masivo generaría de golpe todas las comisiones de los jobs que llegan en PAID,
# fechadas al mes actual.
importando: ContextVar[bool] = ContextVar("importando", default=False)


def _app_id_de(job_type: str, year: int):
    return str((PODIO_JOB_APPS.get(year, {}).get(job_type) or {}).get("APP_ID") or "")


def _anios_de_la_misma_app(job_type: str, app_id: str) -> list[int]:
    """Los años cuyas credenciales apuntan al mismo app_id.

    En producción devuelve un solo año. En `APP_ENV=test` devuelve los cuatro,
    porque las TAP se reutilizan para todos.
    """
    return sorted(a for a in JOB_YEARS if _app_id_de(job_type, a) == str(app_id))


# Los tipos de campo que sirven para auditar una métrica. Se filtra por TIPO y no
# por una lista de `external_id` a propósito: en cuanto eliges qué campo es «lo
# cotizado» ya estás usando el mapeo del código que la auditoría tiene que poner
# a prueba. Bajando todos los numéricos, el mapeo se reconstruye después desde
# las etiquetas de Podio y queda como artefacto revisable.
# `category` entra porque el estado del job decide qué filas suma cada métrica;
# `date` para poder contrastar la regla del año contra su origen.
TIPOS_AUDITABLES = {"money", "number", "calculation",
                    "progress", "category", "date"}


def _campos_crudos(item: dict) -> dict:
    """Los valores tal como los devuelve Podio, sin pasar por el mapeador.

    Se conserva `values` sin tocar (Podio anida distinto según el tipo: money da
    `{"value","currency"}`, category da `{"value":{"text"}}`) porque normalizar
    aquí sería volver a meter criterio propio en el lado que hace de patrón.
    """
    crudos = {}
    for campo in item.get("fields") or []:
        if campo.get("type") not in TIPOS_AUDITABLES:
            continue
        crudos[campo.get("external_id")] = {
            "label": campo.get("label"),
            "type": campo.get("type"),
            "values": campo.get("values"),
        }
    return crudos


def _enumerar(servicio, total_esperado: int, offset_inicial: int = 0,
              presupuesto_s: int | None = None,
              campos: bool = False) -> tuple[dict, int | None, dict]:
    """Pagina la app. Devuelve (ids -> clave formateada, siguiente_offset, crudos).

    `crudos` va vacío salvo con `campos=true`. No cuesta red: la página ya trae
    el ítem entero (ver abajo), así que hasta ahora se estaba tirando.

    `siguiente_offset` es None cuando se termino la app; un entero cuando se
    agoto el presupuesto de reloj y hay que reencadenar desde ahi.

    El presupuesto NO es opcional en la practica. Medido contra produccion el
    11-ago-2026: el filtro de Podio devuelve el item COMPLETO, con todos sus
    campos, asi que una pagina de 500 tarda unos 100 s en construirse del lado
    de Podio. QID2026 (1267 items, 3 paginas) tardo 296,6 s — al borde del
    techo de 300 s de la funcion. QID2025 tiene 1880 y NO cabria: sin trocear,
    las tres apps QID grandes son sencillamente inverificables.
    """
    items, offset = {}, offset_inicial
    crudos = {}
    inicio = time.monotonic()
    while True:
        if presupuesto_s is not None and offset > offset_inicial:
            # Se comprueba ANTES de pedir otra pagina, con el coste de la
            # ultima como estimacion de la siguiente.
            gastado = time.monotonic() - inicio
            por_pagina = gastado / max(1, (offset - offset_inicial) / TOPE_PAGINA)
            if gastado + por_pagina > presupuesto_s:
                return items, offset, crudos

        pagina = servicio.get_items_page(limit=TOPE_PAGINA, offset=offset)
        lote = pagina.get("items") or []
        if not lote:
            break
        for item in lote:
            iid = str(item.get("item_id"))
            items[iid] = item.get("app_item_id_formatted")
            if campos:
                crudos[iid] = _campos_crudos(item)
        offset += len(lote)
        if len(items) + offset_inicial >= (total_esperado or 0) and total_esperado:
            break
        if len(lote) < TOPE_PAGINA:
            break
    return items, None, crudos


def _conteo_bd(session, job_type: str, anios: list[int],
               solo_con_item: bool = False) -> int:
    """Filas de la BD para (tipo, años).

    Con `solo_con_item` cuenta unicamente las que tienen `podio_item_id`, que
    son las UNICAS que pueden emparejar con un item de Podio. Es la cifra que
    hay que comparar contra el contador de la app: incluir los jobs locales
    hace que un local TAPE un item ausente y el semaforo salga verde.
    """
    filtros = [Job.Job_type == job_type, expr_anio_app().in_(anios)]
    if solo_con_item:
        filtros.append(Job.podio_item_id.is_not(None))
    return session.exec(
        select(func.count()).select_from(Job).where(*filtros)
    ).one()


def _paridad_de_app(session, job_type: str, year: int, enumerar: bool,
                    offset: int = 0, presupuesto_s: int | None = None,
                    campos: bool = False) -> dict:
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
            # Solo estas pueden emparejar con un item; es contra esta que se
            # compara Podio. La diferencia con por_anio son los jobs locales.
            "con_item_id": _conteo_bd(session, job_type,
                                      [year] if comparable else colapsados,
                                      solo_con_item=True),
        },
        "apps_colapsadas": colapsados if not comparable else [],
        "comparable_por_anio": comparable,
    }
    resultado["bd"]["locales_sin_item"] = (
        resultado["bd"]["por_anio" if comparable else "por_app_id"]
        - resultado["bd"]["con_item_id"])

    # El lado de la BD con el que se compara depende de si la app está partida
    # por año de verdad o no. Comparar contra `por_anio` en dev es comparar la
    # misma app de Podio contra un cuarto de la BD.
    #
    # Y se compara contra con_item_id, NO contra por_anio: medido el 11-ago-2026
    # en produccion, PTL2026 daba delta 0 y ok=true mientras a la BD le FALTABA
    # el item PTL6024 — el hueco lo tapaba el job local PTL-I60001. El criterio
    # por conteo bruto es un falso positivo esperando a pasar.
    resultado["delta"] = (total_podio or 0) - resultado["bd"]["con_item_id"]
    # Lo que el cliente ve en el panel incluye los locales, asi que se expone
    # aparte para explicar por que su cuenta a ojo puede no cuadrar todavia.
    resultado["delta_visible_en_panel"] = (
        (total_podio or 0)
        - resultado["bd"]["por_anio" if comparable else "por_app_id"])

    if not comparable:
        resultado["nota"] = (
            f"APP_ENV=test: los años {colapsados} comparten el app_id {app_id}. "
            f"La comparación válida aquí es podio.total contra bd.por_app_id; "
            f"la paridad por año solo puede demostrarse contra credenciales reales."
        )

    if enumerar:
        encontrados, siguiente, crudos = _enumerar(
            servicio, total_podio, offset_inicial=offset,
            presupuesto_s=presupuesto_s, campos=campos)
        resultado["podio"]["enumerados"] = len(encontrados)
        resultado["podio"]["offset"] = offset
        resultado["podio"]["items"] = [
            {"item_id": i, "app_item_id_formatted": c,
             **({"campos": crudos.get(i, {})} if campos else {})}
            for i, c in encontrados.items()]

        if siguiente is not None:
            # Se acabo el reloj antes que la app. No es un fallo ni una
            # paridad: es media medida, y decirlo es la unica opcion honesta.
            resultado["siguiente_offset"] = siguiente
            resultado["completo"] = False
            resultado["ok"] = False
            resultado["parcial"] = (
                f"enumerados {len(encontrados)} de {total_podio} antes de agotar "
                f"el presupuesto. Reencadenar con offset={siguiente}.")
            return resultado

        resultado["completo"] = True
        if offset:
            # Vino troceada: esta llamada solo tiene su ultimo tramo, asi que
            # comparar contra la BD entera daria un `faltan` inventado.
            resultado["ok"] = False
            resultado["parcial"] = (
                "tramo final de una enumeracion troceada: la comparacion la "
                "hace quien acumule todos los tramos.")
            return resultado

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

    # El veredicto usa la evidencia MAS fuerte disponible. Si se enumero, los
    # conjuntos mandan sobre el conteo: dos errores que se compensan dan delta
    # 0 y no son paridad. Sin enumerar, el conteo es lo unico que hay, y por
    # eso `ok` sin `enumerar=true` es una condicion NECESARIA, no suficiente.
    resultado["ok"] = resultado.get("ok", True) and resultado["delta"] == 0
    if enumerar:
        resultado["ok"] = (
            resultado["ok"]
            and not resultado["faltan"]
            and not resultado["sobran"]
            and not resultado["desalineados"])
    else:
        resultado["veredicto_parcial"] = (
            "solo conteo: coincidir aqui es necesario pero no suficiente. "
            "Usa enumerar=true para comparar los conjuntos.")
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
    offset = request.args.get("offset", default=0, type=int)
    presupuesto = request.args.get("presupuesto_s", default=PRESUPUESTO_S, type=int)
    # Solo para auditar: añade a cada item sus campos numéricos crudos, tal cual
    # los da Podio. Sirve para calcular las métricas desde el origen sin pasar
    # por el mapeador ni por la BD — comparar la BD contra sí misma no prueba
    # nada sobre los valores. Encarece la respuesta, no la red.
    campos = (request.args.get("campos") or "").lower() in ("1", "true", "yes")

    if campos and not enumerar:
        return jsonify({"detail": "campos=true requiere enumerar=true"}), 400
    if offset and not (tipo and anio):
        return jsonify({"detail": "offset solo tiene sentido con type y year"}), 400
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
                    filas.append(_paridad_de_app(
                        session, t, a, enumerar,
                        offset=offset, presupuesto_s=presupuesto,
                        campos=campos))
                except Exception as e:  # una app rota no puede tumbar el censo
                    errores.append({"tipo": t, "anio": a,
                                    "error": f"{type(e).__name__}: {e}"})

    return jsonify({
        "filas": filas,
        "errores": errores,
        "ok": bool(filas) and not errores and all(f.get("ok") for f in filas),
        "enumerado": enumerar,
    }), 200


def _token_confirmacion(claves) -> str:
    """sha256 del conjunto exacto que se enseñó en el dry-run.

    El operador pide `dry_run`, recibe el token y lo devuelve para ejecutar. Si
    el conjunto cambió entre mirar y borrar — porque un webhook entregó algo en
    medio — el token no casa y se rechaza. Nunca se borra un conjunto distinto
    del que se enseñó.
    """
    material = "|".join(sorted(str(c) for c in claves))
    return hashlib.sha256(f"{len(claves)}:{material}".encode()).hexdigest()


# Las 7 columnas que alimentan las 8 tarjetas del dashboard. Deliberadamente NO
# se reconcilia nada más: nombres, fechas y relaciones tienen su propio camino de
# sync y meterlas aquí convierte una reparación acotada en una reescritura.
COLUMNAS_DINERO = (
    "Gqm_target_sold_pricing",
    "Gqm_formula_pricing",
    "Gqm_adj_formula_pricing",
    "Gqm_final_sold_pricing",
    "Gqm_premium_in_money",
    "Gqm_target_return",
    "Gqm_final_percentage",
)

# Los importes son float en la BD y texto decimal en Podio: comparar con `!=`
# marca como divergente medio censo por el ruido del binario.
TOLERANCIA = 0.005


def _difiere(bd, podio) -> bool:
    if bd is None and podio is None:
        return False
    if bd is None or podio is None:
        return True
    try:
        return abs(float(bd) - float(podio)) > TOLERANCIA
    except (TypeError, ValueError):
        return str(bd) != str(podio)


def _a_float(v):
    """Podio manda los importes como texto: `{"value": "1980.0100"}`.

    Sin esto se escribiría la cadena en una columna float. Postgres la castea y
    el UPDATE funciona, pero el objeto en memoria se queda con un str hasta el
    siguiente refresh, y cualquier comparación posterior en la misma sesión
    compara texto contra número.
    """
    if v is None or isinstance(v, float):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _diff_de_job(job, valores_podio: dict) -> dict:
    """Columnas de dinero donde la BD se ha ido de Podio. Podio manda."""
    cambios = {}
    for col in COLUMNAS_DINERO:
        if col not in valores_podio:
            continue  # el campo no existe en esa app; no es divergencia
        actual = getattr(job, col, None)
        nuevo = _a_float(valores_podio[col])
        if _difiere(actual, nuevo):
            cambios[col] = {"bd": actual, "podio": nuevo}
    return cambios


@paridad_bp.post("/import")
@handle_exceptions()
def importar():
    """Trae una app-año de Podio a la BD. `dry_run=true` por defecto.

    Va por `upsert_job_from_item`, el MISMO motor que el webhook: empareja por
    `podio_item_id OR ID_Jobs` y degrada INSERT→UPDATE dentro de un
    `begin_nested()`. Eso importa porque 2026 está vivo: mientras se importa,
    los hooks siguen entregando los mismos items. Un COPY masivo perdería esa
    carrera; esto la gana por diseño.

    Presupuesto por reloj: procesa hasta agotar la app o hasta quedarse sin
    margen para otra página, y devuelve `siguiente_offset` para reencadenar.
    """
    from src.podio.webhook.jobs_hook_sync import upsert_job_from_item

    tipo = (request.args.get("type") or "").upper().strip()
    anio = request.args.get("year", type=int)
    offset = request.args.get("offset", default=0, type=int)
    presupuesto = request.args.get("presupuesto_s", default=PRESUPUESTO_S, type=int)
    dry_run = (request.args.get("dry_run") or "true").lower() not in ("0", "false", "no")
    # `items=3289271527,3289263246` importa SOLO esos item_id. Sin esto, reparar
    # 3 jobs ausentes de QID2026 obliga a reescribir los 1264 que ya estaban
    # bien: radio de explosion gratis sobre produccion. Con el filtro, lo que
    # se toca es exactamente lo que el censo dijo que faltaba.
    solo_items = {s.strip() for s in (request.args.get("items") or "").split(",")
                  if s.strip()}

    if tipo not in JOB_TYPES or anio not in JOB_YEARS:
        return jsonify({"detail": f"type y year obligatorios. "
                                  f"Válidos: {JOB_TYPES} / {JOB_YEARS}"}), 400

    servicio = podio_jobs_router.get_readonly_service(tipo, anio)
    inicio = time.monotonic()
    resumen = {"tipo": tipo, "anio": anio, "dry_run": dry_run, "offset_inicial": offset,
               "procesados": 0, "creados": 0, "actualizados": 0,
               "errores": [], "siguiente_offset": None,
               "agotado_por_presupuesto": False,
               "filtro_items": sorted(solo_items) or None,
               "saltados_por_filtro": 0}

    vistos: set[str] = set()
    ficha = importando.set(True)
    try:
        with get_session() as session:
            comisiones_antes = session.exec(
                select(func.count()).select_from(CommissionDetail)).one()
            resumen["podio_total"] = servicio.get_items_page(limit=1).get("filtered")

            while True:
                if time.monotonic() - inicio + MARGEN_PAGINA_S > presupuesto:
                    resumen["agotado_por_presupuesto"] = True
                    resumen["siguiente_offset"] = offset
                    break

                pagina = servicio.get_items_page(limit=TOPE_PAGINA, offset=offset)
                lote = pagina.get("items") or []
                if not lote:
                    break

                if solo_items:
                    lote = [i for i in lote
                            if str(i.get("item_id")) in solo_items]
                    vistos.update(str(i.get("item_id")) for i in lote)
                    resumen["saltados_por_filtro"] += (
                        len(pagina.get("items") or []) - len(lote))

                punto = session.begin_nested()
                for item in lote:
                    try:
                        existia = session.exec(
                            select(Job.ID_Jobs).where(
                                Job.podio_item_id == str(item.get("item_id")))).first()
                        upsert_job_from_item(session, item, tipo, anio)
                        resumen["actualizados" if existia else "creados"] += 1
                        resumen["procesados"] += 1
                    except Exception as e:
                        resumen["errores"].append({
                            "item_id": item.get("item_id"),
                            "error": f"{type(e).__name__}: {e}"})

                if dry_run:
                    # Se revierte SIEMPRE: el dry-run informa de lo que habría
                    # pasado, nunca lo deja a medias.
                    punto.rollback()
                else:
                    punto.commit()
                    # Un commit por página: si la cuarta falla, las tres
                    # primeras no se pierden.
                    session.commit()

                offset += len(pagina.get("items") or [])
                if solo_items and resumen["procesados"] >= len(solo_items):
                    # Ya estan todos: no tiene sentido seguir paginando la app.
                    break
                if len(pagina.get("items") or []) < TOPE_PAGINA:
                    break

            if solo_items:
                # Un item pedido que Podio no tiene es un dato, no un silencio:
                # o se borro en Podio, o el item_id venia mal.
                resumen["no_encontrados_en_podio"] = sorted(
                    solo_items - vistos) or None
                if resumen["no_encontrados_en_podio"]:
                    resumen["errores"].append({
                        "item_id": None,
                        "error": f"pedidos pero no estan en la app: "
                                 f"{resumen['no_encontrados_en_podio']}"})

            comisiones_despues = session.exec(
                select(func.count()).select_from(CommissionDetail)).one()
            resumen["comisiones"] = {"antes": comisiones_antes,
                                     "despues": comisiones_despues}
            if comisiones_antes != comisiones_despues:
                # Criterio medible del plan: si se mueve un registro, se para.
                resumen["errores"].append({
                    "item_id": None,
                    "error": f"IMPORTAR GENERÓ COMISIONES ({comisiones_antes} → "
                             f"{comisiones_despues}). Se para: se habrían fechado "
                             f"al mes actual sobre jobs históricos."})
    finally:
        importando.reset(ficha)

    resumen["segundos"] = round(time.monotonic() - inicio, 1)
    resumen["ok"] = not resumen["errores"]
    return jsonify(resumen), 200 if resumen["ok"] else 409


@paridad_bp.post("/reconciliar_dinero")
@handle_exceptions()
def reconciliar_dinero():
    """Reescribe desde Podio las columnas de dinero que se han ido de su origen.

    El defecto que esto repara, medido en producción el 14-ago-2026: 185 jobs con
    `Gqm_formula_pricing = 0` en la BD teniendo Podio un valor real, con venta
    distinta de 0 y sin cancelar. 167 son de 2026. Como el premium se deriva
    (`final − formula` en PTL, `final − adj` en QID/PAR), perder la fórmula
    infla el premium por el mismo importe: en PAR2026 faltan $110.681 de fórmula
    y sobran $110.064 de premium.

    Sync y mapeo están BIEN — en 2023 los seis agregados de QID coinciden al
    céntimo. Lo que falla es posterior: los agregados son columnas almacenadas
    que sólo se recalculan al escribir hijos por la API (`job_calculator.py::
    recalculate_and_apply`), y `create_job` no recalcula. Un job que entra por
    webhook sin que sus órdenes crucen la API se queda con la fórmula en 0.

    Reconciliación unidireccional Podio → BD, como manda el cliente. Solo UPDATE
    sobre filas que ya existen: nunca crea ni borra, ni aquí ni en Podio (el
    servicio es de solo lectura). `dry_run=true` por defecto, y aplicar exige el
    `confirmar=<sha>` del dry-run previo, así que no se puede escribir un
    conjunto distinto del que se enseñó.

    NO toca el mapeo. En PTL, `Gqm_target_sold_pricing` sale del campo etiquetado
    «PTL Cost» (job_fields_map.py:172) y por eso TOTAL QUOTED enseña un coste;
    cambiarlo mueve dinero en pantalla y es decisión de negocio, no de una
    reparación de datos.
    """
    tipo = (request.args.get("type") or "").upper().strip()
    anio = request.args.get("year", type=int)
    dry_run = (request.args.get("dry_run") or "true").lower() not in ("0", "false", "no")
    confirmar = request.args.get("confirmar")
    presupuesto = request.args.get("presupuesto_s", default=PRESUPUESTO_S, type=int)

    if tipo not in JOB_TYPES or anio not in JOB_YEARS:
        return jsonify({"detail": f"type y year obligatorios. "
                                  f"Válidos: {JOB_TYPES} / {JOB_YEARS}"}), 400

    from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job

    servicio = podio_jobs_router.get_readonly_service(tipo, anio)
    sonda = servicio.get_items_page(limit=1)
    total_podio = sonda.get("filtered") or sonda.get("total") or 0

    # Igual que en purge_orphans: de una página parcial no se concluye nada.
    # Aquí es menos grave (solo se dejarían jobs sin reparar) pero un informe a
    # medias que parece completo es justo lo que hace perder la tarde.
    inicio, items, offset = time.monotonic(), [], 0
    while True:
        pagina = servicio.get_items_page(limit=TOPE_PAGINA, offset=offset)
        lote = pagina.get("items") or []
        if not lote:
            break
        items.extend(lote)
        offset += len(lote)
        if len(items) >= total_podio or len(lote) < TOPE_PAGINA:
            break
        if time.monotonic() - inicio > presupuesto:
            return jsonify({
                "detail": f"enumerados {len(items)} de {total_podio} antes de "
                          "agotar el presupuesto. No se reconcilia con datos "
                          "parciales.", "parcial": True}), 409

    if len(items) != total_podio:
        return jsonify({
            "detail": "la enumeración no cuadra con la sonda; la app se movió "
                      "mientras se contaba. No se toca nada.",
            "sonda": total_podio, "enumerados": len(items)}), 409

    diffs, sin_fila = [], []
    with get_session() as session:
        por_item = {
            str(j.podio_item_id): j
            for j in session.exec(
                select(Job).where(Job.Job_type == tipo,
                                  Job.podio_item_id.is_not(None),
                                  expr_anio_app() == anio)).all()
        }

        for item in items:
            job = por_item.get(str(item.get("item_id")))
            if job is None:
                sin_fila.append(item.get("app_item_id_formatted"))
                continue
            cambios = _diff_de_job(job, map_podio_item_to_job(item, job_type=tipo))
            if cambios:
                diffs.append({"ID_Jobs": job.ID_Jobs, "cambios": cambios})

        token = _token_confirmacion(
            [f"{d['ID_Jobs']}:{sorted(d['cambios'])}" for d in diffs])

        if dry_run:
            return jsonify({
                "dry_run": True, "tipo": tipo, "anio": anio,
                "items_podio": len(items), "jobs_a_tocar": len(diffs),
                "sin_fila_en_bd": sin_fila, "confirmar": token,
                "diffs": diffs}), 200

        if confirmar != token:
            return jsonify({
                "detail": "el conjunto cambió entre el dry-run y ahora: el token "
                          "no casa. Vuelve a pedir el dry_run y usa su token.",
                "confirmar_esperado": token}), 409

        # `importando` corta la generación de comisiones en el PATCH de jobs:
        # reparar un agregado no puede pagar a nadie dos veces.
        marca = importando.set(True)
        try:
            for d in diffs:
                job = next(j for j in por_item.values() if j.ID_Jobs == d["ID_Jobs"])
                for col, v in d["cambios"].items():
                    setattr(job, col, v["podio"])
                session.add(job)
            session.commit()
        finally:
            importando.reset(marca)

    return jsonify({"dry_run": False, "tipo": tipo, "anio": anio,
                    "jobs_actualizados": len(diffs),
                    "ID_Jobs": [d["ID_Jobs"] for d in diffs]}), 200


@paridad_bp.post("/purge_orphans")
@handle_exceptions()
def purgar_huerfanas():
    """Borra jobs cuyo `podio_item_id` ya no existe en su app de Podio.

    Exige la enumeración COMPLETA de la app: de una página parcial no se infiere
    ausencia. Y exige `confirmar=<sha>` del dry-run previo.
    """
    tipo = (request.args.get("type") or "").upper().strip()
    anio = request.args.get("year", type=int)
    dry_run = (request.args.get("dry_run") or "true").lower() not in ("0", "false", "no")
    confirmar = request.args.get("confirmar")

    if tipo not in JOB_TYPES or anio not in JOB_YEARS:
        return jsonify({"detail": f"type y year obligatorios. "
                                  f"Válidos: {JOB_TYPES} / {JOB_YEARS}"}), 400

    servicio = podio_jobs_router.get_readonly_service(tipo, anio)
    sonda = servicio.get_items_page(limit=1)
    total_podio = sonda.get("filtered") or sonda.get("total") or 0
    # Desempaquetado explícito: esto era `encontrados = _enumerar(...)`, que
    # dejaba la TUPLA en la variable. `len(tupla)` es 2, no el número de items,
    # así que la guarda de abajo comparaba 2 contra el total y saltaba siempre —
    # por eso nunca se notó. Pero si una app llegaba a tener exactamente 2 items
    # la guarda pasaba, y entonces `str(item_id) not in encontrados` (línea de
    # los candidatos) probaba pertenencia contra la tupla en vez de contra el
    # dict: TODOS los jobs de ese tipo/año salían huérfanos, en un endpoint que
    # borra con cascada de 4 niveles.
    encontrados, siguiente, _ = _enumerar(servicio, total_podio)

    if siguiente is not None or len(encontrados) != total_podio:
        return jsonify({
            "detail": "la enumeración no cuadra con la sonda; la app se movió "
                      "mientras se contaba. No se borra nada.",
            "sonda": total_podio, "enumerados": len(encontrados)}), 409

    with get_session() as session:
        colapsados = _anios_de_la_misma_app(tipo, str(servicio.app_id))
        anios = colapsados if len(colapsados) > 1 else [anio]
        candidatos = [
            j for j in session.exec(
                select(Job).where(Job.Job_type == tipo,
                                  Job.podio_item_id.is_not(None),
                                  expr_anio_app().in_(anios))).all()
            if str(j.podio_item_id) not in encontrados
        ]

        token = _token_confirmacion([j.ID_Jobs for j in candidatos])
        detalle = [inventario_dependientes(session, j) for j in candidatos]

        if dry_run:
            return jsonify({"dry_run": True, "tipo": tipo, "anio": anio,
                            "huerfanas": len(candidatos), "confirmar": token,
                            "detalle": detalle}), 200

        if confirmar != token:
            return jsonify({
                "detail": "el conjunto cambió entre el dry-run y ahora: el token "
                          "no casa. Vuelve a pedir el dry_run y usa su token.",
                "confirmar_esperado": token}), 409

        antes = sentinela_huerfanos(session)
        borrados = []
        try:
            for job in candidatos:
                borrar_job_sin_huerfanos(session, job)
                borrados.append(job.ID_Jobs)
            session.commit()
        except HuerfanosCreados as e:
            session.rollback()
            return jsonify({"detail": str(e), "revertido": True}), 409

        return jsonify({"dry_run": False, "borrados": borrados,
                        "huerfanos": {"antes": antes,
                                      "despues": sentinela_huerfanos(session)},
                        "detalle": detalle}), 200


@paridad_bp.delete("/local_jobs/<path:id_job>")
@handle_exceptions()
def borrar_local(id_job):
    """Borra un job local, exigiendo declarar cuántos dependientes arrastra.

    `?dependientes_esperados=<n>` es la confirmación explícita, mecanizada en
    vez de verbal: el número solo se conoce leyendo el dry-run. Los vacíos pasan
    con `n=0`; `QID-I60001` (56 estimate_cost, 1 CO, 2 purchases, 57 actividad)
    obliga a escribir su número.
    """
    esperados = request.args.get("dependientes_esperados", type=int)
    if esperados is None:
        return jsonify({"detail": "falta ?dependientes_esperados=<n>. Pide antes "
                                  "GET /admin/podio/local_jobs/<id> para saberlo."}), 400

    with get_session() as session:
        job = session.exec(select(Job).where(Job.ID_Jobs == id_job)).first()
        if not job:
            return jsonify({"detail": f"no existe el job {id_job}"}), 404
        if job.podio_item_id:
            return jsonify({
                "detail": f"{id_job} tiene podio_item_id ({job.podio_item_id}): no es "
                          f"un job local. Borrarlo aquí rompería la paridad."}), 409

        inventario = inventario_dependientes(session, job)
        if inventario["total_dependientes"] != esperados:
            return jsonify({
                "detail": f"declaraste {esperados} dependientes y hay "
                          f"{inventario['total_dependientes']}. No se borra.",
                "inventario": inventario}), 409

        try:
            resultado = borrar_job_sin_huerfanos(session, job)
            session.commit()
        except HuerfanosCreados as e:
            session.rollback()
            return jsonify({"detail": str(e), "revertido": True}), 409

    return jsonify({"borrado": id_job, **resultado}), 200


@paridad_bp.get("/local_jobs/<path:id_job>")
@handle_exceptions()
def inspeccionar_local(id_job):
    """Dry-run de un borrado: la fila y todo lo que arrastra en las 10 tablas."""
    with get_session() as session:
        job = session.exec(select(Job).where(Job.ID_Jobs == id_job)).first()
        if not job:
            return jsonify({"detail": f"no existe el job {id_job}"}), 404
        return jsonify(inventario_dependientes(session, job)), 200


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
