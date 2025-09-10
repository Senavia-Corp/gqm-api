# ---------------------- EJEMPLO DE API ----------------------
import os
import json
import datetime as dt
from flask import Flask, jsonify, request
import requests
from dotenv import load_dotenv

# ======== Carga .env ========
load_dotenv()

# ======== Config Podio ========
BASE_URL = "https://api.podio.com"
TOKEN_URL = "https://api.podio.com/oauth/token/v2"

PODIO_CLIENT_ID = os.getenv("PODIO_CLIENT_ID")
PODIO_CLIENT_SECRET = os.getenv("PODIO_CLIENT_SECRET")
PODIO_APP_ID = os.getenv("PODIO_APP_ID")
PODIO_APP_TOKEN = os.getenv("PODIO_APP_TOKEN")

# Validaciones básicas
_missing = [k for k, v in {
    "PODIO_CLIENT_ID": PODIO_CLIENT_ID,
    "PODIO_CLIENT_SECRET": PODIO_CLIENT_SECRET,
    "PODIO_APP_ID": PODIO_APP_ID,
    "PODIO_APP_TOKEN": PODIO_APP_TOKEN,
}.items() if not v]
if _missing:
    print(f"[WARN] Faltan variables en .env: {', '.join(_missing)}")

app = Flask(__name__)

# ----------------- TUS RUTAS ORIGINALES -----------------
@app.route('/')
def root():
    return "Home"

@app.route("/jobs/<job_id>")
def get_user(job_id):
    jobs = {
        "id": job_id,
        "Job_type": "Construction",
        "Project_Name": "Miami Residential Tower",
        "Project_Location": "1234 Biscayne Blvd, Miami, FL 33132, USA",
        "Job_Status": "In Progress",
        "PO_WTN_WO_QID": "PO-98321",
        "Service_Type": "Structural Engineering",
        "Date_Assigned": "2025-08-15",
        "Estimated_Start_Date": "2025-09-01",
        "Estimated_Project_Duration": "180 days",
        "GQM_Formula_Pricing": 1250000.00,
        "GQM_Adj_Formula_Pricing": 1285000.00,
        "GQM_Target_Sold_Pricing": 1350000.00,
        "GQM_Premium_in_$": 50000.00,
        "GQM_Final_Sold_Pricing": 1400000.00,
        "GQM_Final_%": 12.5,
        "GQM_Total_Change_Orders_QID": 3,
        "ID_Member": "MBR1022",
        "ID_Cliente": "CLI2099"
    }
    query = request.args.get("query")
    if query:
        jobs["query"] = query
    return jsonify(jobs), 200

@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    data["status"] = "user created"
    return jsonify(data), 201

# ----------------- UTILIDADES PODIO -----------------
class PodioError(Exception):
    pass

def get_app_token():
    """
    App Auth: obtiene access_token con grant_type=app.
    """
    try:
        payload = {
            "grant_type": "app",
            "app_id": int(PODIO_APP_ID),
            "app_token": PODIO_APP_TOKEN,
            "client_id": PODIO_CLIENT_ID,
            "client_secret": PODIO_CLIENT_SECRET,
            "redirect_uri": "https://example.com/callback"
        }
        r = requests.post(TOKEN_URL, json=payload, timeout=20)
        r.raise_for_status()
        return r.json()["access_token"]
    except requests.HTTPError as e:
        raise PodioError(f"Error autenticando con Podio: {e.response.text}") from e

def get_app_fields(access_token):
    """
    Lee definición del App y arma:
      - ext_by_label: {label_normalizado: external_id}
      - meta_by_ext:  {external_id: {...}}
      - id_to_ext:    {field_id: external_id}
    """
    try:
        url = f"{BASE_URL}/app/{PODIO_APP_ID}"
        r = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
        r.raise_for_status()
        app_json = r.json()
    except requests.HTTPError as e:
        raise PodioError(f"Error leyendo App: {e.response.text}") from e

    ext_by_label, meta_by_ext, id_to_ext = {}, {}, {}

    for f in app_json.get("fields", []):
        ext = f.get("external_id")
        ftype = f.get("type")
        fid = f.get("field_id")
        label = (f.get("config", {}) or {}).get("label", "")
        label_key = label.strip().lower().replace(" ", "_")

        # opciones de categoría
        category_options = {}
        if ftype in ("category", "question"):
            settings = (f.get("config", {}) or {}).get("settings", {}) or {}
            for opt in settings.get("options", []) or []:
                if isinstance(opt, dict) and "id" in opt and "text" in opt:
                    category_options[opt["text"]] = opt["id"]

        if isinstance(ext, str):
            ext_by_label[label_key] = ext
            meta_by_ext[ext] = {
                "type": ftype,
                "field_id": fid,
                "label": label,
                "category_options": category_options
            }
            if fid is not None:
                id_to_ext[fid] = ext

    return app_json.get("fields", []), {
        "ext_by_label": ext_by_label,
        "meta_by_ext": meta_by_ext,
        "id_to_ext": id_to_ext,
    }

def build_demo_fields_payload(meta_by_ext):
    """
    Arma un payload de ejemplo en base a los PRIMEROS campos disponibles por tipo.
    - text      -> "Hola desde API (App Auth)"
    - number    -> "123.45"
    - date      -> start_date = hoy (YYYY-MM-DD)
    - category  -> primera opción disponible (option_id)
    """
    payload_fields = {}

    def first_field_of(ftype):
        for ext, meta in meta_by_ext.items():
            if meta["type"] == ftype:
                return ext, meta
        return None, None

    # TEXT
    ext, meta = first_field_of("text")
    if ext:
        payload_fields[ext] = {"value": "Hola desde API (App Auth)"}

    # NUMBER
    ext, meta = first_field_of("number")
    if ext:
        payload_fields[ext] = {"value": "123.45"}

    # DATE
    ext, meta = first_field_of("date")
    if ext:
        payload_fields[ext] = {"start_date": dt.date.today().isoformat()}

    # CATEGORY
    ext, meta = first_field_of("category")
    if ext and meta["category_options"]:
        first_opt_id = next(iter(meta["category_options"].values()))
        payload_fields[ext] = {"value": first_opt_id}

    return payload_fields

def create_item(access_token, fields_payload, external_id=None, hook=True, silent=False):
    """
    Crea un ítem en el App con los campos proporcionados.
    fields_payload: dict con keys = external_id de campos del App.
    """
    try:
        url = f"{BASE_URL}/item/app/{PODIO_APP_ID}/"
        body = {"fields": fields_payload}
        if external_id:
            body["external_id"] = external_id

        params = {"hook": str(hook).lower(), "silent": str(silent).lower()}
        r = requests.post(
            url,
            params=params,
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30
        )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        raise PodioError(f"Error creando ítem: {e.response.text}") from e

# ======== LISTAR ÍTEMS (con filtro por vista y paginación) ========
def _fetch_items_page(access_token, limit=100, offset=0, view_id=None):
    """
    Trae una página de ítems del App usando el endpoint de filtros.
    - Si pasas view_id, aplica esa vista guardada.
    - limit máx. efectivo: 500
    Retorna: lista de items (cada item trae fields, item_id, title, etc.)
    """
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    if view_id:
        url = f"{BASE_URL}/item/app/{PODIO_APP_ID}/filter/{int(view_id)}/"
        body = {"limit": limit, "offset": offset}
    else:
        url = f"{BASE_URL}/item/app/{PODIO_APP_ID}/filter/"
        # body vacío = todos los ítems del app
        body = {"limit": limit, "offset": offset, "filters": {}}

    r = requests.post(url, json=body, headers=headers, timeout=40)
    r.raise_for_status()
    data = r.json()
    # El endpoint suele responder {"items": [...], ...}
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    # fallback por si alguna versión responde lista
    if isinstance(data, list):
        return data
    return []

def _normalize_item(item, meta_by_ext, id_to_ext, category_mode="both"):
    """
    Convierte item["fields"] (lista) en dict por external_id con valores amigables.
    Usa id_to_ext cuando el external_id no viene en la respuesta.
    """
    out = {
        "item_id": item.get("item_id"),
        "title": item.get("title"),
    }
    for k in ("created_on", "last_event_on", "link", "app_item_id_formatted"):
        if k in item:
            out[k] = item[k]

    fields_out = {}

    def _coerce_int(x):
        if isinstance(x, int):
            return x
        if isinstance(x, str) and x.isdigit():
            return int(x)
        return None

    def resolve_external_id(field_obj):
        # 1) Si viene bien formado como string, úsalo
        ext = field_obj.get("external_id")
        if isinstance(ext, str):
            return ext

        # 2) A veces viene anidado como dict o lista: intenta extraer string
        if isinstance(ext, dict):
            for k in ("external_id", "value", "id"):
                v = ext.get(k)
                if isinstance(v, str):
                    return v
        if isinstance(ext, list):
            for el in ext:
                if isinstance(el, str):
                    return el
                if isinstance(el, dict):
                    for k in ("external_id", "value", "id"):
                        v = el.get(k)
                        if isinstance(v, str):
                            return v

        # 3) Fallback por field_id -> external_id usando id_to_ext
        fid = field_obj.get("field_id")
        if isinstance(fid, dict):
            # ejemplos: {"id": 123}, {"field_id": 123}, {"value": 123}
            for k in ("field_id", "id", "value"):
                v = fid.get(k)
                fid_int = _coerce_int(v)
                if fid_int is not None:
                    return id_to_ext.get(fid_int)
            return None

        fid_int = _coerce_int(fid)
        if fid_int is not None:
            return id_to_ext.get(fid_int)

        # 4) No se pudo resolver
        return None

    for f in item.get("fields", []):
        ext = resolve_external_id(f)
        if not isinstance(ext, str) or not ext:
            # No pudimos mapear el campo -> lo saltamos
            continue

        ftype = f.get("type")
        values = f.get("values") or []
        meta = meta_by_ext.get(ext, {})
        result = None

        def one(v):
            if ftype in ("text", "location", "calculation"):
                return v.get("value")
            if ftype == "number":
                return v.get("value")
            if ftype == "date":
                return {
                    "start": v.get("start"),
                    "start_date": v.get("start_date"),
                    "end": v.get("end"),
                    "end_date": v.get("end_date"),
                }
            if ftype in ("category", "question"):
                opt_id = v.get("value")
                opt_text = v.get("text")
                if not opt_text and isinstance(meta.get("category_options"), dict):
                    inv = {oid: t for t, oid in meta["category_options"].items()}
                    opt_text = inv.get(opt_id)
                if category_mode == "text":
                    return opt_text
                if category_mode == "id":
                    return opt_id
                return {"id": opt_id, "text": opt_text}
            if ftype in ("app", "contact"):
                return v.get("value") or v
            return v.get("value", v)

        if not values:
            result = None
        elif len(values) == 1:
            result = one(values[0])
        else:
            result = [one(v) for v in values]

        fields_out[ext] = result

    out["fields"] = fields_out
    return out

def list_items(access_token, meta_by_ext, limit=200, offset=0, fetch_all=False, view_id=None):
    """
    Orquesta la paginación. Si fetch_all=True, recorre todas las páginas en bloques de 500.
    """
    items = []
    if fetch_all:
        page = 0
        while True:
            page_items = _fetch_items_page(access_token, limit=500, offset=page*500, view_id=view_id)
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < 500:
                break
            page += 1
        return items

    # modo paginado simple
    return _fetch_items_page(access_token, limit=limit, offset=offset, view_id=view_id)


# ----------------- RUTAS PODIO (para probar fácil) -----------------
@app.route("/podio/fields", methods=["GET"])
def podio_fields():
    """
    Devuelve el mapeo: label -> external_id, y meta por external_id (tipo, opciones categoría).
    """
    try:
        token = get_app_token()
        _, maps = get_app_fields(token)
        return jsonify(maps), 200
    except PodioError as e:
        return jsonify({"error": str(e)}), 502
    
@app.route("/podio/items", methods=["GET"])
def podio_list_items():
    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
        fetch_all = str(request.args.get("all", "false")).lower() in ("1", "true", "yes")
        view_id = request.args.get("view_id")
        fmt = (request.args.get("format") or "normalized").lower()
        category_mode = (request.args.get("category_mode") or "both").lower()

        token = get_app_token()
        _, maps = get_app_fields(token)

        raw_items = list_items(
            token,
            maps["meta_by_ext"],
            limit=limit,
            offset=offset,
            fetch_all=fetch_all,
            view_id=view_id
        )

        if fmt == "raw":
            return jsonify({"count": len(raw_items), "items": raw_items}), 200

        normalized = [
            _normalize_item(it, maps["meta_by_ext"], maps["id_to_ext"], category_mode=category_mode)
            for it in raw_items
        ]
        return jsonify({
            "count": len(normalized),
            "items": normalized,
            "view_id": view_id,
            "fetch_all": fetch_all
        }), 200

    except requests.HTTPError as e:
        return jsonify({"error": f"Podio API: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/podio/items/demo", methods=["POST"])
def podio_create_demo_item():
    """
    Crea un ítem de prueba:
    - Si el body trae "fields", se usa tal cual.
    - Si no, se arma un payload demo automáticamente.
    Body opcional:
      { "fields": {...}, "external_id": "mi-id-externo", "hook": true, "silent": false }
    """
    try:
        body = request.get_json(silent=True) or {}
        token = get_app_token()
        _, maps = get_app_fields(token)

        fields_payload = body.get("fields") or build_demo_fields_payload(maps["meta_by_ext"])
        external_id = body.get("external_id")
        hook = bool(body.get("hook", True))
        silent = bool(body.get("silent", False))

        created = create_item(token, fields_payload, external_id=external_id, hook=hook, silent=silent)
        return jsonify(created), 201
    except PodioError as e:
        return jsonify({"error": str(e)}), 502

@app.route("/podio/items", methods=["POST"])
def podio_create_item_custom():
    """
    Crea un ítem con los "fields" EXACTOS que envíes.
    Body requerido:
      { "fields": { "<external_id>": {...}, ... }, "external_id": "opcional" }
    """
    try:
        body = request.get_json(force=True)
        fields_payload = body.get("fields")
        if not isinstance(fields_payload, dict) or not fields_payload:
            return jsonify({"error": "Body debe incluir 'fields' (dict) con al menos un campo."}), 400

        token = get_app_token()
        external_id = body.get("external_id")
        created = create_item(token, fields_payload, external_id=external_id)
        return jsonify(created), 201
    except PodioError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"Body inválido: {str(e)}"}), 400

# ----------------- MAIN -----------------
if __name__=='__main__':
    app.run(debug=True)
