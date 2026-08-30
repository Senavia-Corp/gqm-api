"""Carga UNICA de la app de Podio «Supplier/Distributor» a la tabla `supplier`.

Un solo sentido: Podio -> PostgreSQL. NO es un sync, no instala webhooks, no
escribe en Podio jamas. Se ejecuta a mano, cuatro fases que paran solas.

    cd ~/gqm-work/api          # SIEMPRE desde aqui: es donde vive el .env

    # Fase 1 — catalogo de campos de Podio y propuesta de mapeo. PARA.
    PODIO_READONLY=true PODIO_SUPPLIER_APP_ID=... PODIO_SUPPLIER_APP_TOKEN=... \
      .venv/bin/python scripts/migrar_suppliers_podio.py --esquema

    # Fase 2 — simulacro. Lee Podio y la BD. CERO escrituras. PARA.
    ... GQM_PROD_DATABASE_URL=... .venv/bin/python scripts/migrar_suppliers_podio.py --dry-run

    # Fase 3 — carga real, una sola transaccion.
    ... .venv/bin/python scripts/migrar_suppliers_podio.py --aplicar

    # Fase 4 — diff BD <-> Podio. Solo lectura, reejecutable siempre.
    ... .venv/bin/python scripts/migrar_suppliers_podio.py --verificar

`--ensayo-develop` en cualquier fase exige que la BD sea Neon develop; sin el
flag, exige que NO lo sea. La guarda es BIDIRECCIONAL a proposito: asi no hay
forma de confundir el sentido.

NO REDIRIJAS LA SALIDA A UN FICHERO. `get_podio_headers` imprime el app_id por
stdout (podio_auth.py:107). El token no sale nunca, pero el app_id sí.

Las credenciales van SIEMPRE por prefijo de entorno, nunca en .env ni aqui.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import os
import pathlib
import sys
import time
from contextlib import contextmanager
from urllib.parse import urlparse

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# La restriccion de cwd no es ceremonia. Desde otro directorio `load_dotenv()`
# no encuentra el .env, `APP_ENV` cae a "production" (config.py:29) y la lista
# blanca de apps de Podio queda VACIA — y esa guarda esta escrita
# `if permitidas and str(app_id) not in permitidas` (podio_base_services.py:84),
# o sea que una lista vacia la DESACTIVA. Falla abierta.
if pathlib.Path.cwd() != RAIZ:
    sys.exit(f"⛔ ejecuta desde {RAIZ} (cwd actual: {pathlib.Path.cwd()}).\n"
             f"   Desde otro cwd no se carga el .env y la guarda de escritura "
             f"de Podio falla ABIERTA.")

import psycopg2  # noqa: E402
import requests  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

import src.config as cfg  # noqa: E402
from src.config import BASE_URL  # noqa: E402
from src.podio.podio_auth import get_podio_headers  # noqa: E402
from src.podio.services.podio_base_services import PodioReadOnlyService  # noqa: E402
from src.utils.mappers.mapper_aux_functions import clean_html  # noqa: E402
from src.utils.mappers.podio_value_extractor import get_podio_field_value  # noqa: E402

# OJO: `src.database.db_sqlmodel` NO se importa en ninguna linea de este fichero,
# y no hay que importarlo. Crea el engine AL IMPORTARSE (db_sqlmodel.py:14) con
# el DATABASE_URL del .env — que es el de DEVELOP. Manteniendolo fuera, en este
# proceso hay exactamente UNA conexion a Postgres: la que abre `conectar()`
# despues de la guarda. Verificado que la cadena de Podio no lo arrastra.

# ---------------------------------------------------------------- constantes

COLUMNAS = ["ID_Supplier", "podio_item_id", "Company_Name", "Company_Website",
            "Description", "Acc_Status", "Acc_Rep", "Speciality",
            "Email_Address", "Coverage_Area", "Phone_Number", "Address"]

# Columnas que se rellenan desde Podio (todas menos la PK, que se calcula).
COLUMNAS_PODIO = [c for c in COLUMNAS if c != "ID_Supplier"]

PREFIJO = "SUP"
SENTINEL_DEVELOP = "ep-sparkling-sound"  # el mismo de tests/conftest.py:10

# Vocabularios cerrados del panel (app/suppliers/create/page.tsx:18-30).
# Se usan SOLO para informar de diferencias; el script no fuerza nada.
PANEL_ACC_STATUS = {"Active", "Inactive"}
PANEL_SPECIALTIES = {
    "Doors", "Windows/Glazing", "Plumbing Materials", "Fencing",
    "Landscaping Supplies", "Tile/Flooring", "Stones/Masonry", "Rental Equip",
    "Electrical Materials", "HVAC Materials", "Paint Suppliers", "Roll Up Doors",
    "Kitchen Cabinets", "Roofing Materials", "Glass/Mirrors",
    "Construction Supplies", "Bathroom Supplies", "Gutters / Screens",
}
PANEL_COVERAGE_AREAS = {
    "Dade County", "Broward County", "Palm Beach County", "St. Lucie County",
    "Orange County", "Seminole County", "Pinellas County (St Pete)",
    "Hillsborough County (Tampa)", "Osceola County",
}

# ===========================================================================
# MAPEO — SE RELLENA EN EL GATE DE LA FASE 1, NO SE ADIVINA
# ===========================================================================
# columna de `supplier` -> lista de external_id / label de Podio a probar.
# `get_podio_field_value` empareja por external_id O por label, ambos
# case-insensitive, asi que vale cualquiera de los dos.
#
# Nacio vacio a proposito: la Fase 1 imprime una PROPUESTA calculada contra el
# esquema real, y las fases 2-4 se niegan a correr mientras siga vacio.
#
# RELLENADO EN EL GATE DE LA FASE 1 (29-ago-2026, app 29517937, 56 items).
# Dos entradas NO son las que propuso el emparejador automatico:
#   - Speciality -> `contractor-type`: en Podio el campo se llama «Specilty»
#     (con la errata), asi que no casaba por nombre. La columna de la BD tiene
#     su propia errata distinta («Speciality»). Ninguna se toca.
#   - Acc_Rep -> `job-title`: el label es «Acc Rep/ Other». Es tipo `text`, NO
#     `contact` — que era el riesgo de extractor ciego. Confirmado por el
#     diagnostico: el unico campo ciego es `photo`, y no se carga.
#
# Se dejan FUERA a proposito tres campos de la app:
#   - `field` (label «--», type calculation): es un ENCABEZADO DE SECCION
#     falso, de los que Podio pinta con un <h1> dentro de un campo calculado.
#     No es dato.
#   - `photo` (image): extractor ciego y sin columna destino.
#   - `notes` (text): NO EXISTE columna `Notes` en `supplier`. Su contenido no
#     se migra. Meterlo en `Description` seria fusionar dos campos distintos
#     por nuestra cuenta.
CAMPOS: dict[str, list[str]] = {
    "Company_Name":    ["organization"],      # type tag  -> SIEMPRE lista
    "Company_Website": ["website"],           # type embed
    "Description":     ["name"],              # type text
    "Acc_Status":      ["status"],            # category: Active; Inactive
    "Acc_Rep":         ["job-title"],         # type text
    "Speciality":      ["contractor-type"],   # category, 28 opciones
    "Email_Address":   ["email-address"],     # type email
    "Coverage_Area":   ["coverage-area"],     # category, 9 opciones
    "Phone_Number":    ["phone-number"],      # type phone
    "Address":         ["address"],           # type location
}

# Reescrituras de vocabulario aprobadas por un humano en el gate de la Fase 1.
# Formato: {"Columna": {"valor en Podio": "valor a guardar"}}
#
# Vacio a proposito. Precedente del repo (scripts/sanear_tasks.py): solo se
# arregla lo que tiene correspondencia INEQUIVOCA, porque adivinar datos es
# peor que dejarlos sucios. Lo que no este aqui se carga LITERAL y se lista en
# el informe.
MAPA_VOCABULARIO: dict[str, dict[str, str]] = {}


# ===========================================================================
# Podio — solo lectura, con cuatro capas independientes
# ===========================================================================

@contextmanager
def _sup_en_podio_apps(app_id: str, app_token: str):
    """Mete «SUP» en `PODIO_APPS` SOLO mientras se pide el token, y lo saca.

    `get_podio_headers` resuelve credenciales por `get_podio_app_credentials`
    (config.py:271-278), que lanza ValueError si la clave no esta en el dict.
    Con esta ventana se reutiliza su OAuth, su `@retry_api` y su cache sin
    dejar la app de Supplier dentro de `app_ids_configurados()` — que es la
    LISTA BLANCA DE ESCRITURA que consulta `_verificar_escritura_permitida`.
    Al salir del `with`, para este proceso la app «SUP» vuelve a no existir.

    Las cabeceras hay que sacarlas DENTRO de la ventana: `get_podio_headers`
    consulta las credenciales ANTES que su cache (podio_auth.py:63 vs :86), asi
    que no vale con "calentar" `_token_cache` y salir.
    """
    cfg.PODIO_APPS["SUP"] = {"APP_ID": app_id, "APP_TOKEN": app_token}
    try:
        yield
    finally:
        cfg.PODIO_APPS.pop("SUP", None)


class SupplierPodio(PodioReadOnlyService):
    """Lectura de la app Supplier/Distributor. Escritura imposible por tipo.

    Hereda de `PodioReadOnlyService` (podio_base_services.py:249), no de
    `PodioBaseService`: create/update/delete levantan `EscrituraPodioBloqueada`
    ANTES de tocar la red, aunque TODAS las banderas esten apagadas. Es el
    cinturon que no depende de recordar nada.

    `_headers` congelado: no vuelve a pasar por `PODIO_APPS`, que ya no
    contiene «SUP». El token dura 8 h y esto lee una pagina; si algun dia
    tardara mas, el modo de fallo es un 401 ruidoso, no una escritura.
    """

    def __init__(self, app_id: str, cabeceras: dict):
        super().__init__("SUP", app_id)
        self._cabeceras = cabeceras

    def _headers(self):
        return self._cabeceras


def abrir_podio() -> SupplierPodio:
    app_id = os.environ.get("PODIO_SUPPLIER_APP_ID")
    app_token = os.environ.get("PODIO_SUPPLIER_APP_TOKEN")
    if not app_id or not app_token:
        sys.exit("⛔ faltan PODIO_SUPPLIER_APP_ID / PODIO_SUPPLIER_APP_TOKEN en "
                 "el prefijo del comando (nunca en .env)")
    with _sup_en_podio_apps(app_id, app_token):
        cabeceras = get_podio_headers("SUP")
    return SupplierPodio(app_id, cabeceras)


def esquema_app(svc: SupplierPodio) -> dict:
    """GET /app/{app_id} — el esquema de la app (campos, tipos, opciones).

    No hay helper en el repo para esto: `src/tests/test_get_podio_fields.py`
    esta roto (importa `PODIO_TAP_APP_ID`, simbolo que no existe) y la unica
    llamada funcionante es `scripts/e2e_podio_entrega_real.py:97-100`.
    """
    r = requests.get(f"{BASE_URL}/app/{svc.app_id}",
                     headers=svc._headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def leer_podio(svc: SupplierPodio, esperados: int) -> list[dict]:
    """Los items, en UNA sola pagina y ordenados por item_id.

    Una pagina y no varias: el tope real de Podio es 500
    (`src/routes/podio_routes/Paridad.py:47`, verificado contra la API), 56
    caben de sobra, y al no paginar desaparece la clase de fallo en que un item
    editado a mitad del recorrido se cuela dos veces o se pierde entre offsets.
    """
    pagina = svc.get_items_page(limit=500, offset=0)
    items = pagina["items"]
    total, filtrados = pagina["total"], pagina["filtered"]
    print(f"📥 Podio: recibidos={len(items)} total={total} filtered={filtrados}")

    if not (len(items) == total == filtrados == esperados):
        sys.exit(f"⛔ recuento inesperado (esperaba {esperados}). O el numero de "
                 f"items cambio en Podio, o la app tiene un filtro de vista "
                 f"activo. PARA y decide: si el cambio es legitimo, repite con "
                 f"--esperados {total}.")

    ids = [str(i.get("item_id")) for i in items]
    if len(set(ids)) != len(ids):
        sys.exit("⛔ Podio devolvio item_id repetidos")

    return sorted(items, key=lambda i: int(i["item_id"]))


# ===========================================================================
# Mapeo y normalizacion
# ===========================================================================

def _texto(valor) -> str | None:
    """Cierra la inconsistencia de tipo de `get_podio_field_value`. Y solo eso.

    Ese extractor devuelve tipos distintos segun cuantos valores haya
    (podio_value_extractor.py:78-84): 0 -> None; 1 -> str; >1 sin HTML ->
    **list**; >1 con HTML -> str unido por "\\n". Y los campos `type == "tag"`
    (:40-45) devuelven SIEMPRE lista. La columna destino es `Optional[str]`.
    Los mappers que ya existen (subcontractor_mapper, client_mapper,
    bldg_dept_mapper) no normalizan nada y meterian una `list` en un varchar.

    - list -> elementos limpios unidos por ", ", en el orden de Podio.
    - str  -> `clean_html`, que ya hace `.strip()`.
    - ""   -> None. El panel pinta "—" para los dos y sus guardas son
              `if row.Speciality`, que trata "" como falso: guardar "" solo
              anade un estado que nadie distingue.
              OJO: `clean_html` NO basta para esto. Devuelve None si el valor
              es falsy, pero un valor de SOLO ESPACIOS es truthy, entra, y
              sale como "" (medido: clean_html("   ") == ""). De ahi el
              `or None` final.
    - NO trunca: las 12 columnas son `character varying` SIN longitud
      (verificado en information_schema de produccion).
    - NO reescribe vocabulario, NO anade esquema a URLs, NO reformatea
      telefonos. Eso cambia el dato del cliente: va al informe y al gate.
    """
    if valor is None:
        return None
    if isinstance(valor, list):
        partes = [p for p in (clean_html(v) for v in valor) if p and p.strip()]
        return ", ".join(partes) or None
    return clean_html(valor) or None


def mapear(item: dict) -> dict:
    """Un item crudo de Podio -> una fila de `supplier` (sin ID_Supplier).

    Deja ademas una clave `_multi` con las columnas que en Podio traian VARIOS
    valores. Se anota aqui y no se deduce despues buscando ", " en el texto:
    esa heuristica da falsos positivos con un solo valor que lleve coma
    ("EMS Rolloff, Inc.", cualquier direccion), y el informe del gate es
    justamente donde un falso positivo cuesta caro. `_multi` no llega a la BD:
    `cargar()` construye las tuplas desde COLUMNAS y el CSV ignora las claves
    de mas.
    """
    campos = item.get("fields", [])
    fila = {"podio_item_id": str(item.get("item_id"))}
    multi = []
    for columna in COLUMNAS_PODIO:
        if columna == "podio_item_id":
            continue
        ids = CAMPOS.get(columna) or []
        crudo = get_podio_field_value(campos, ids) if ids else None
        if isinstance(crudo, list) and len(crudo) > 1:
            multi.append(columna)
        bruto = _texto(crudo)
        fila[columna] = MAPA_VOCABULARIO.get(columna, {}).get(bruto, bruto)
    fila["_multi"] = multi
    return fila


def asignar_ids(filas: list[dict], digito: str) -> list[dict]:
    """SUP + digito de anio + contador de 4 cifras. Determinista.

    NO se llama a `generate_custom_id` a proposito. Esa funcion reserva cada
    numero en una CONEXION APARTE que commitea al instante
    (id_generator.py:117,130): 56 llamadas serian 56 commits FUERA de nuestra
    transaccion, y un rollback dejaria `id_counters` en ('SUP','6')=56 con la
    tabla vacia. Es el mismo motivo por el que `sync_orders.py:106` inventa
    "ORD-DRYRUN" en vez de llamarla.

    Con la tabla en 0 (lo exige el preflight) el resultado es identico al que
    daria la funcion, y ademas DETERMINISTA: el dry-run imprime los mismos IDs
    que va a escribir la carga, asi que el rollback.sql existe ANTES de que
    exista el riesgo.

    Y no hace falta sembrar `id_counters`: la siembra perezosa de
    `_siguiente_contador` (id_generator.py:117-138) no encuentra fila
    ('SUP','6'), el UPDATE afecta 0 filas, cae al INSERT ... ON CONFLICT y
    siembra con `_max_actual`, cuya regex `^SUP6[0-9]+$` sobre la tabla real da
    56; GREATEST(...,56)+1 = 57. El primer supplier creado desde el panel sera
    SUP60057. Sin colision posible, y esta carga no escribe en NINGUNA tabla
    que no sea `supplier`.
    """
    for n, fila in enumerate(filas, start=1):
        fila["ID_Supplier"] = f"{PREFIJO}{digito}{n:04d}"
    return filas


def proponer_mapeo(esquema: dict) -> dict[str, list[str]]:
    """Propuesta de CAMPOS a partir del esquema real. Es una PROPUESTA.

    Empareja el nombre de columna normalizado contra el external_id y el label
    de cada campo de Podio. Lo que no case sale vacio y lo decide el humano.
    """
    def norm(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    campos = [f for f in esquema.get("fields", []) if f.get("status") != "deleted"]
    propuesta: dict[str, list[str]] = {}
    for columna in COLUMNAS_PODIO:
        if columna == "podio_item_id":
            continue
        objetivo = norm(columna)
        elegido = None
        for f in campos:
            if norm(f.get("external_id", "")) == objetivo or norm(f.get("label", "")) == objetivo:
                elegido = f["external_id"]
                break
        propuesta[columna] = [elegido] if elegido else []
    return propuesta


# ===========================================================================
# Diagnostico — el bloque que justifica que la Fase 1 exista
# ===========================================================================

def diagnostico_extraccion(items: list[dict], esquema: dict) -> list[tuple]:
    """Campos donde Podio TIENE valor y el extractor devuelve None.

    Es el fallo silencioso mas caro de este camino. Si `Acc Rep` resulta ser un
    campo `contact` y no texto, `get_podio_field_value` entra por la rama de
    lista (:47), hace `val = item.get("value", item)` y obtiene el dict del
    contacto, que no tiene ni "text" ni "value" ni es str: no anade nada a
    `values` y devuelve None (:76-77). Sin error y sin log. Los 56 suppliers
    llegarian con `Acc_Rep` vacio y nadie sabria por que.

    Se detecta contra los `values` CRUDOS, sin fiarse del extractor. Mirar solo
    su salida no lo veria nunca.
    """
    filas = []
    for campo in esquema.get("fields", []):
        if campo.get("status") == "deleted":
            continue
        eid = campo.get("external_id", "")
        con_valor = sum(
            1 for it in items for f in it.get("fields", [])
            if f.get("external_id") == eid and f.get("values")
        )
        extraidos = sum(
            1 for it in items
            if _texto(get_podio_field_value(it.get("fields", []), [eid])) is not None
        )
        ciego = bool(con_valor) and extraidos == 0
        filas.append((eid, campo.get("label", ""), campo.get("type", ""),
                      con_valor, extraidos, ciego))
    return filas


def perfil_columnas(filas: list[dict]) -> list[tuple]:
    """Nulos, distintos, longitud maxima y 3 ejemplos por columna."""
    perfil = []
    for c in COLUMNAS:
        vals = [f.get(c) for f in filas]
        llenos = [v for v in vals if v is not None]
        distintos = sorted({v for v in llenos})
        perfil.append((
            c, len(vals) - len(llenos), len(distintos),
            max((len(v) for v in llenos), default=0),
            distintos[:3],
        ))
    return perfil


def diferencias_vocabulario(filas: list[dict]) -> list[tuple[str, str, int]]:
    """Valores que el panel no sabe pintar. Informativo, no bloquea."""
    catalogos = {
        "Acc_Status": PANEL_ACC_STATUS,
        "Speciality": PANEL_SPECIALTIES,
        "Coverage_Area": PANEL_COVERAGE_AREAS,
    }
    fuera = []
    for columna, catalogo in catalogos.items():
        cuenta: dict[str, int] = {}
        for f in filas:
            v = f.get(columna)
            if v is None:
                continue
            # Multivalor: cada trozo se juzga por separado.
            for trozo in (p.strip() for p in v.split(",")):
                if trozo and trozo not in catalogo:
                    cuenta[trozo] = cuenta.get(trozo, 0) + 1
        fuera += [(columna, v, n) for v, n in sorted(cuenta.items())]
    return fuera


def webs_sin_esquema(filas: list[dict]) -> list[tuple[str, str]]:
    """El detalle del panel mete Company_Website cruda en el href: sin esquema,
    el navegador la resuelve como ruta RELATIVA. Se reporta, no se reescribe:
    poner https:// es inventar."""
    return [(f["podio_item_id"], f["Company_Website"]) for f in filas
            if f.get("Company_Website")
            and not f["Company_Website"].lower().startswith(("http://", "https://"))]


# ===========================================================================
# Base de datos — psycopg2 directo
# ===========================================================================

def conectar(ensayo: bool):
    """Abre la UNICA conexion del proceso, tras la guarda bidireccional.

    Variable SEPARADA (`GQM_PROD_DATABASE_URL`, no `DATABASE_URL`) a proposito,
    como en `scripts/rbac_spec_produccion.py:30-38`: un DATABASE_URL exportado
    por costumbre en la shell no puede apuntar este script a ningun sitio.
    """
    url = os.environ.get("GQM_PROD_DATABASE_URL")
    if not url:
        sys.exit("⛔ falta GQM_PROD_DATABASE_URL en el entorno.\n"
                 "   Exportala con `read -s GQM_PROD_DATABASE_URL; export GQM_PROD_DATABASE_URL`")
    host = urlparse(url).hostname or "?"
    es_develop = SENTINEL_DEVELOP in host

    if ensayo and not es_develop:
        sys.exit(f"⛔ --ensayo-develop exige la BD de develop, y host={host} no lo es")
    if not ensayo and es_develop:
        sys.exit(f"⛔ host={host} es develop. Si es intencional, usa --ensayo-develop")

    print(f"🔌 host={host} · entorno={'DEVELOP (ensayo)' if es_develop else 'PRODUCCION'}")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn, ("develop" if es_develop else "prod")


def comprobar_esquema(cur):
    """Las columnas de la BD REAL, no las que el modelo SQLModel cree tener."""
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='supplier'")
    reales = {r[0] for r in cur.fetchall()}
    if reales != set(COLUMNAS):
        raise RuntimeError(f"columnas de la BD != esperadas. "
                           f"Diferencia: {reales ^ set(COLUMNAS)}")


def contadores(cur) -> dict:
    """Baseline de las tablas vecinas: prueba que no se escribio fuera."""
    cur.execute("""
        SELECT (SELECT count(*) FROM supplier),
               (SELECT count(*) FROM id_counters WHERE prefix = %s),
               (SELECT count(*) FROM purchase),
               (SELECT count(*) FROM purchase_supplier),
               (SELECT count(*) FROM attachments)
    """, (PREFIJO,))
    s, ic, p, ps, a = cur.fetchone()
    return {"supplier": s, "id_counters_SUP": ic, "purchase": p,
            "purchase_supplier": ps, "attachments": a}


def respaldar(cur, destino: pathlib.Path) -> dict:
    """CSV de `supplier` antes de tocar nada, y sha256 de las tablas vecinas.

    Mismo patron que `respaldar()` en scripts/rbac_spec_produccion.py:87-111.
    """
    csv_antes = destino / "supplier-antes.csv"
    buf = io.StringIO()
    cur.copy_expert(
        'COPY (SELECT ' + ", ".join(f'"{c}"' for c in COLUMNAS) +
        ' FROM supplier ORDER BY "ID_Supplier") '
        "TO STDOUT WITH (FORMAT csv, HEADER, NULL '\\N')", buf)
    csv_antes.write_text(buf.getvalue(), encoding="utf-8")
    sha = hashlib.sha256(buf.getvalue().encode()).hexdigest()
    return {"csv": csv_antes, "sha256": sha, "bytes": len(buf.getvalue())}


def cargar(cur, filas: list[dict]):
    """Todo dentro de la transaccion del llamador. Todo o nada.

    El preflight va AQUI, en la misma transaccion que escribe, no antes: entre
    un chequeo externo y el INSERT cabe otra escritura.
    """
    # 1. la tabla tiene que estar virgen
    cur.execute("SELECT count(*) FROM supplier")
    n = cur.fetchone()[0]
    if n != 0:
        raise RuntimeError(
            f"`supplier` tiene {n} filas y esperaba 0. PARA. Si la carga ya se "
            f"hizo, usa --verificar; no reintentes --aplicar.")

    # 2. nadie ha creado suppliers por el panel entre medias
    cur.execute("SELECT count(*) FROM id_counters WHERE prefix = %s", (PREFIJO,))
    if cur.fetchone()[0] != 0:
        raise RuntimeError("`id_counters` ya tiene contador SUP: alguien creo "
                           "suppliers desde el panel. PARA.")

    # 3. red por CLAVE NATURAL. Redundante con (1) hoy, pero `podio_item_id`
    #    no tiene indice UNICO (verificado: ix_supplier_podio_item_id es
    #    indisunique=false) y anadirlo exigiria Alembic, que esta prohibido.
    cur.execute("SELECT podio_item_id FROM supplier WHERE podio_item_id = ANY(%s)",
                ([f["podio_item_id"] for f in filas],))
    ya = [r[0] for r in cur.fetchall()]
    if ya:
        raise RuntimeError(f"{len(ya)} podio_item_id ya presentes ({ya[:5]}...). PARA.")

    # 4. el esquema real
    comprobar_esquema(cur)

    # 5. el INSERT
    execute_values(
        cur,
        "INSERT INTO supplier (" + ", ".join(f'"{c}"' for c in COLUMNAS) + ") VALUES %s",
        [tuple(f[c] for c in COLUMNAS) for f in filas],
    )
    if cur.rowcount != len(filas):
        raise RuntimeError(f"rowcount={cur.rowcount}, esperaba {len(filas)}")

    # 6. relectura ANTES del commit (patron rbac_spec_produccion.py:178-181)
    cur.execute("SELECT " + ", ".join(f'"{c}"' for c in COLUMNAS) +
                ' FROM supplier ORDER BY "ID_Supplier"')
    leidas = cur.fetchall()
    esperadas = sorted((tuple(f[c] for c in COLUMNAS) for f in filas),
                       key=lambda t: t[0])
    if leidas != esperadas:
        raise RuntimeError("la relectura no coincide con lo insertado")


# ===========================================================================
# Salidas
# ===========================================================================

def escribir_csv(ruta: pathlib.Path, filas: list[dict]):
    with ruta.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        for f in filas:
            w.writerow({c: f.get(c) for c in COLUMNAS})


def escribir_rollback(ruta: pathlib.Path, filas: list[dict], host: str, sello: str):
    ids = ",\n              ".join(
        ", ".join(f"'{f['ID_Supplier']}'" for f in filas[i:i + 6])
        for i in range(0, len(filas), 6))
    ruta.write_text(f"""-- Rollback de la carga unica de suppliers desde Podio.
-- Generado: {sello} · host={host} · {len(filas)} filas
--
-- attachments."ID_Supplier" y purchase_supplier.supplier_id son ON DELETE
-- NO ACTION (confdeltype='a', verificado en pg_constraint): si a estas alturas
-- alguien ha enlazado un adjunto o una compra a estos suppliers, este DELETE
-- FALLA en vez de destruirlo. Si falla: PARA. Alguien esta usando los datos.
--
-- NUNCA convertir esto en TRUNCATE ni en un DELETE sin WHERE.
-- `id_counters` no se toco en la carga: no hay nada que revertir ahi.
BEGIN;
DELETE FROM public.supplier
 WHERE "ID_Supplier" IN ({ids});
-- esperado: DELETE {len(filas)}. Si el numero no coincide: ROLLBACK y reportar.
COMMIT;
""", encoding="utf-8")


def escribir_informe(ruta: pathlib.Path, secciones: list[tuple[str, str]]):
    ruta.write_text("\n\n".join(f"## {t}\n\n{c}" for t, c in secciones) + "\n",
                    encoding="utf-8")


def tabla_md(cabeceras: list[str], filas) -> str:
    out = ["| " + " | ".join(cabeceras) + " |",
           "|" + "|".join("---" for _ in cabeceras) + "|"]
    for f in filas:
        out.append("| " + " | ".join(
            str(v).replace("|", "\\|").replace("\n", " ") for v in f) + " |")
    return "\n".join(out)


# ===========================================================================
# Fases
# ===========================================================================

def fase1(args, salida: pathlib.Path):
    svc = abrir_podio()
    esquema = esquema_app(svc)
    items = leer_podio(svc, args.esperados)

    campos = [f for f in esquema.get("fields", []) if f.get("status") != "deleted"]
    cat = []
    for f in campos:
        conf = f.get("config") or {}
        opts = (conf.get("settings") or {}).get("options") or []
        cat.append((f.get("external_id"), f.get("label"), f.get("type"),
                    "si" if conf.get("required") else "",
                    "; ".join(str(o.get("text")) for o in opts) if opts else ""))

    diag = diagnostico_extraccion(items, esquema)
    ciegos = [d for d in diag if d[5]]
    propuesta = proponer_mapeo(esquema)
    reclamados = {e for ids in propuesta.values() for e in ids}
    huerfanos = [(f.get("external_id"), f.get("label"), f.get("type"))
                 for f in campos if f.get("external_id") not in reclamados]

    literal = "CAMPOS = {\n" + "".join(
        f'    {c!r}: {ids!r},\n' for c, ids in propuesta.items()) + "}"

    escribir_informe(salida / "informe-fase1.md", [
        ("Cabecera", tabla_md(["clave", "valor"], [
            ("sello", args.sello), ("app_id de Podio", svc.app_id),
            ("items", len(items)), ("APP_ENV", cfg.APP_ENV),
            ("PODIO_READONLY", cfg.PODIO_READONLY),
            ("apps en la lista blanca", len(cfg.app_ids_configurados())),
        ])),
        ("Catalogo de campos de la app",
         tabla_md(["external_id", "label", "type", "req", "opciones"], cat)),
        ("Diagnostico de extraccion",
         "Cuenta cuantos items tienen valor CRUDO en el campo frente a cuantos "
         "consigue extraer `get_podio_field_value` + `_texto`. Una linea con "
         "`SI` en la ultima columna es un **extractor ciego**: Podio tiene el "
         "dato y el extractor devuelve None sin error ni log.\n\n" +
         tabla_md(["external_id", "label", "type", "con_valor", "extraidos", "CIEGO"],
                  [(a, b, c, d, e, "SI" if f else "") for a, b, c, d, e, f in diag])),
        ("Campos de Podio que ninguna columna reclama",
         tabla_md(["external_id", "label", "type"], huerfanos) if huerfanos
         else "Ninguno."),
        ("Propuesta de CAMPOS (pegar en el script tras aprobarla)",
         "```python\n" + literal + "\n```"),
    ])

    print(f"\n📄 {salida / 'informe-fase1.md'}")
    print("\n" + literal)
    sin_mapear = [c for c, ids in propuesta.items() if not ids]
    if sin_mapear:
        print(f"\n⚠️  columnas sin campo propuesto: {', '.join(sin_mapear)}")
    if ciegos:
        print(f"\n🚨 EXTRACTOR CIEGO en {len(ciegos)} campo(s): "
              f"{', '.join(d[0] for d in ciegos)}")
        print("   Podio tiene valor y el extractor devuelve None, sin error.")
        print("   NO apruebes el gate si alguno de esos campos se va a cargar.")
    print("\n⏸  GATE DE LA FASE 1. Revisa el informe, rellena CAMPOS y "
          "MAPA_VOCABULARIO, y entonces corre --dry-run.")


def _exigir_mapeo():
    if not CAMPOS:
        sys.exit("⛔ CAMPOS esta vacio. Corre --esquema primero y rellena el "
                 "mapeo aprobado en el gate de la Fase 1.")


def _preparar_filas(args) -> tuple[list[dict], list[dict]]:
    svc = abrir_podio()
    items = leer_podio(svc, args.esperados)
    excluidos = set(args.excluir.split(",")) if args.excluir else set()
    items = [i for i in items if str(i["item_id"]) not in excluidos]
    if excluidos:
        print(f"➖ excluidos {len(excluidos)} items por --excluir")
    return items, asignar_ids([mapear(i) for i in items], args.digito)


def fase2(args, salida: pathlib.Path):
    _exigir_mapeo()
    items, filas = _preparar_filas(args)

    conn, entorno = conectar(args.ensayo_develop)
    try:
        with conn.cursor() as cur:
            comprobar_esquema(cur)
            base = contadores(cur)
    finally:
        conn.rollback()
        conn.close()

    escribir_csv(salida / "previsto.csv", filas)
    escribir_rollback(salida / "rollback.sql", filas, entorno, args.sello)

    fuera = diferencias_vocabulario(filas)
    webs = webs_sin_esquema(filas)
    multi = [(f["podio_item_id"], c, f[c]) for f in filas for c in f.get("_multi", [])]
    vacios = [f["podio_item_id"] for f in filas if not f.get("Company_Name")]
    nbsp = [(f["podio_item_id"], c) for f in filas for c in COLUMNAS_PODIO
            if isinstance(f.get(c), str) and "\xa0" in f[c]]

    escribir_informe(salida / "informe-fase2.md", [
        ("Cabecera", tabla_md(["clave", "valor"], [
            ("sello", args.sello), ("entorno", entorno),
            ("digito de anio", args.digito), ("filas a cargar", len(filas)),
            ("primer ID", filas[0]["ID_Supplier"] if filas else "-"),
            ("ultimo ID", filas[-1]["ID_Supplier"] if filas else "-"),
        ])),
        ("Baseline de la BD (debe quedar identico salvo `supplier`)",
         tabla_md(["tabla", "filas"], base.items())),
        ("Perfil por columna",
         tabla_md(["columna", "nulos", "distintos", "long_max", "ejemplos"],
                  perfil_columnas(filas))),
        ("DECISIONES PENDIENTES · vocabulario que el panel no sabe pintar",
         tabla_md(["columna", "valor en Podio", "items"], fuera) if fuera
         else "Ninguno: todo cae en los catalogos del panel."),
        ("DECISIONES PENDIENTES · campos multivalor unidos por ', '",
         tabla_md(["podio_item_id", "columna", "valor"], multi) if multi
         else "Ninguno."),
        ("DECISIONES PENDIENTES · Company_Website sin esquema",
         tabla_md(["podio_item_id", "valor"], webs) if webs
         else "Ninguna: todas traen http:// o https://."),
        ("DECISIONES PENDIENTES · Company_Name vacio",
         ", ".join(vacios) if vacios else "Ninguno."),
        ("DECISIONES PENDIENTES · espacio no separable (\\xa0)",
         tabla_md(["podio_item_id", "columna"], nbsp) if nbsp else "Ninguno."),
        ("Mapeo final",
         tabla_md(["podio_item_id", "ID_Supplier", "Company_Name"],
                  [(f["podio_item_id"], f["ID_Supplier"], f.get("Company_Name"))
                   for f in filas])),
    ])

    print(f"\n📄 {salida / 'informe-fase2.md'}")
    print(f"📄 {salida / 'rollback.sql'}  (ya escrito, ANTES de escribir nada)")
    print(f"📄 {salida / 'previsto.csv'}")
    print(f"\n⏸  GATE DE LA FASE 2. Cero escrituras hechas. "
          f"Revisa el informe y entonces corre --aplicar.")


def fase3(args, salida: pathlib.Path):
    _exigir_mapeo()
    items, filas = _preparar_filas(args)

    rollback = salida / "rollback.sql"
    if not rollback.exists():
        sys.exit(f"⛔ no existe {rollback}. Corre --dry-run antes: el rollback "
                 f"tiene que existir ANTES de escribir.")
    if filas and filas[0]["ID_Supplier"] not in rollback.read_text():
        sys.exit(f"⛔ el rollback.sql de {salida} no menciona "
                 f"{filas[0]['ID_Supplier']}. Es de otra corrida (o cambio el "
                 f"digito de anio). Repite --dry-run.")

    conn, entorno = conectar(args.ensayo_develop)
    if entorno == "prod":
        print("⚠️  ESCRITURA EN PRODUCCION. Ctrl-C en 10 s para abortar.")
        time.sleep(10)

    try:
        with conn.cursor() as cur:
            antes = contadores(cur)
            resp = respaldar(cur, salida)
            cargar(cur, filas)
            despues = contadores(cur)
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        sys.exit(f"⛔ ABORTADO, rollback completo. Nada se escribio.\n   {e}")
    conn.close()

    escribir_csv(salida / "cargado.csv", filas)
    (salida / "manifest.txt").write_text(
        f"sello={args.sello}\nentorno={entorno}\n"
        f"respaldo={resp['csv'].name} sha256={resp['sha256']} bytes={resp['bytes']}\n"
        + "".join(f"antes.{k}={v}\n" for k, v in antes.items())
        + "".join(f"despues.{k}={v}\n" for k, v in despues.items()),
        encoding="utf-8")

    intactas = [k for k in antes if k != "supplier" and antes[k] != despues[k]]
    print(f"\n✅ {len(filas)} filas en `supplier` ({entorno}).")
    print(tabla_md(["tabla", "antes", "despues"],
                   [(k, antes[k], despues[k]) for k in antes]))
    if intactas:
        print(f"\n🚨 tablas vecinas alteradas: {intactas} — INVESTIGA")
    print(f"\n📄 {salida / 'manifest.txt'}\n📄 {salida / 'cargado.csv'}")


def fase4(args, salida: pathlib.Path):
    _exigir_mapeo()
    items, filas = _preparar_filas(args)
    esperado = {f["podio_item_id"]: f for f in filas}

    conn, entorno = conectar(args.ensayo_develop)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT " + ", ".join(f'"{c}"' for c in COLUMNAS) +
                        " FROM supplier")
            real = {r[1]: dict(zip(COLUMNAS, r)) for r in cur.fetchall()}
            cuentas = contadores(cur)
    finally:
        conn.rollback()
        conn.close()

    faltan = sorted(set(esperado) - set(real))
    sobran = sorted(set(real) - set(esperado))
    difs = []
    for pid in sorted(set(esperado) & set(real)):
        for c in COLUMNAS_PODIO:
            if esperado[pid].get(c) != real[pid].get(c):
                difs.append((pid, c, esperado[pid].get(c), real[pid].get(c)))

    escribir_informe(salida / "verificacion.md", [
        ("Cabecera", tabla_md(["clave", "valor"], [
            ("sello", args.sello), ("entorno", entorno),
            ("en Podio", len(esperado)), ("en la BD", len(real)),
        ])),
        ("Contadores", tabla_md(["tabla", "filas"], cuentas.items())),
        ("En Podio y no en la BD", ", ".join(faltan) or "Ninguno."),
        ("En la BD y no en Podio", ", ".join(sobran) or "Ninguno."),
        ("Diferencias campo a campo",
         tabla_md(["podio_item_id", "columna", "Podio", "BD"], difs) if difs
         else "Ninguna."),
    ])

    ok = not (faltan or sobran or difs) and cuentas["supplier"] == len(esperado)
    print(tabla_md(["tabla", "filas"], cuentas.items()))
    print(f"\nfaltan={len(faltan)} sobran={len(sobran)} diferencias={len(difs)}")
    print(f"📄 {salida / 'verificacion.md'}")
    print("\n✅ VERIFICADO" if ok else "\n🚨 HAY DIFERENCIAS — revisa el informe")
    return 0 if ok else 1


# ===========================================================================

def autotest() -> int:
    """Autochequeo de la logica pura. Sin red, sin BD, sin credenciales.

    Cubre lo que puede romperse en SILENCIO: la normalizacion de tipos, la
    numeracion determinista y que el rollback salga acotado. No cubre las
    fases, que necesitan Podio y Postgres.
    """
    # _texto: el retorno de get_podio_field_value es str | list | None
    assert _texto(None) is None
    assert _texto("  hola  ") == "hola"
    assert _texto("") is None
    assert _texto("   ") is None, "un valor de solo espacios tiene que ser NULL"
    assert _texto([]) is None
    assert _texto(["Doors", "Fencing"]) == "Doors, Fencing", "categoria multiple"
    assert _texto(["Doors", "", None, "  "]) == "Doors", "trozos vacios fuera"
    assert _texto(["Solo"]) == "Solo"

    # asignar_ids: mismo formato que id_generator, y determinista
    filas = [{"podio_item_id": str(i)} for i in range(1, 57)]
    ids = [f["ID_Supplier"] for f in asignar_ids(filas, "6")]
    assert ids[0] == "SUP60001" and ids[-1] == "SUP60056"
    assert len(set(ids)) == 56
    assert ids == [f["ID_Supplier"] for f in asignar_ids(filas, "6")], "no determinista"

    # diferencias_vocabulario: juzga cada trozo del multivalor por separado
    f = [{"podio_item_id": "1", "Acc_Status": "Activo", "Speciality": "Doors, Marcianos",
          "Coverage_Area": "Dade County"}]
    fuera = {(c, v) for c, v, _ in diferencias_vocabulario(f)}
    assert ("Acc_Status", "Activo") in fuera, "minuscula/idioma != Active"
    assert ("Speciality", "Marcianos") in fuera
    assert ("Speciality", "Doors") not in fuera, "Doors si esta en el catalogo"
    assert ("Coverage_Area", "Dade County") not in fuera

    # webs_sin_esquema: solo las que el navegador resolveria como relativas
    w = webs_sin_esquema([{"podio_item_id": "1", "Company_Website": "www.a.com"},
                          {"podio_item_id": "2", "Company_Website": "https://b.com"},
                          {"podio_item_id": "3", "Company_Website": None}])
    assert [p for p, _ in w] == ["1"]

    # rollback: acotado, con todos los IDs, y sin ninguna forma destructiva
    import tempfile
    ruta = pathlib.Path(tempfile.mkdtemp()) / "rollback.sql"
    escribir_rollback(ruta, asignar_ids(filas, "6"), "host-de-prueba", "sello")
    sql = ruta.read_text()
    assert all(i in sql for i in ids), "faltan IDs en el rollback"
    # Solo las SENTENCIAS: la cabecera menciona TRUNCATE y DELETE a proposito,
    # para prohibirlos. Si se mira el fichero entero, la asercion se dispara
    # con el comentario que la respalda.
    stmts = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "TRUNCATE" not in stmts.upper(), "el rollback no puede truncar"
    assert stmts.count("DELETE") == 1, "una sola sentencia de borrado"
    assert 'WHERE "ID_Supplier" IN' in stmts, "el DELETE tiene que ir acotado"

    print("✅ autotest: 22 aserciones OK")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Carga unica de Supplier/Distributor de Podio a `supplier`.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--esquema", action="store_true", help="Fase 1: catalogo y gate")
    g.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="Fase 2: simulacro, cero escrituras")
    g.add_argument("--aplicar", action="store_true", help="Fase 3: carga real")
    g.add_argument("--verificar", action="store_true", help="Fase 4: diff BD<->Podio")
    g.add_argument("--autotest", action="store_true",
                   help="autochequeo de la logica pura (sin red ni BD)")
    p.add_argument("--ensayo-develop", action="store_true", dest="ensayo_develop",
                   help="exige que la BD sea Neon develop (sin el flag, exige que NO lo sea)")
    p.add_argument("--dir", default="~/outputs/gqm-suppliers")
    p.add_argument("--esperados", type=int, default=56)
    p.add_argument("--excluir", default="", help="podio_item_id separados por coma")
    args = p.parse_args()

    # Antes de las guardas: no toca red, ni BD, ni credenciales.
    if args.autotest:
        return autotest()

    # La bandera se lee de `os.getenv` en config.py:45 y `load_dotenv()` no pisa
    # lo que ya esta en el entorno, asi que el prefijo del comando manda.
    if not cfg.PODIO_READONLY:
        sys.exit("⛔ falta PODIO_READONLY=true en el prefijo del comando.\n"
                 "   Es la bandera que corta TODA escritura saliente a Podio.")
    if len(cfg.app_ids_configurados()) < 7:
        sys.exit(f"⛔ la lista blanca de Podio tiene "
                 f"{len(cfg.app_ids_configurados())} apps: el .env no se cargo. "
                 f"Esa guarda falla ABIERTA cuando queda vacia.")

    args.sello = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.digito = str(dt.datetime.now().year)[-1]

    salida = pathlib.Path(args.dir).expanduser() / (
        "develop" if args.ensayo_develop else "prod")
    salida.mkdir(parents=True, exist_ok=True)

    if args.esquema:
        return fase1(args, salida) or 0
    if args.dry_run:
        return fase2(args, salida) or 0
    if args.aplicar:
        return fase3(args, salida) or 0
    return fase4(args, salida)


if __name__ == "__main__":
    sys.exit(main())
