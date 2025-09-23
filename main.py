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

# ----------------- UTILIDAD: eliminar nulls recursivamente -----------------
def prune_nulls(obj, drop_empty=False):
    """
    Elimina recursivamente:
      - claves con valor None en dicts
      - elementos None en listas
    Si drop_empty=True, también elimina dicts/listas que queden vacíos.
    Mantiene 0/False/'': no se consideran null.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if v is None:
                continue
            v2 = prune_nulls(v, drop_empty=drop_empty)
            if drop_empty and (v2 == {} or v2 == []):
                continue
            out[k] = v2
        return out
    if isinstance(obj, list):
        out = [prune_nulls(v, drop_empty=drop_empty) for v in obj if v is not None]
        if drop_empty:
            out = [v for v in out if not (v == {} or v == [])]
        return obj
    return obj

# ----------------- TUS RUTAS ORIGINALES -----------------
@app.route('/')
def root():
    return "Home"

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
    """
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    if view_id:
        url = f"{BASE_URL}/item/app/{PODIO_APP_ID}/filter/{int(view_id)}/"
        body = {"limit": limit, "offset": offset}
    else:
        url = f"{BASE_URL}/item/app/{PODIO_APP_ID}/filter/"
        body = {"limit": limit, "offset": offset, "filters": {}}

    r = requests.post(url, json=body, headers=headers, timeout=40)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []

def _normalize_item(item, meta_by_ext, id_to_ext, category_mode="both"):
    """
    Convierte item["fields"] (lista) en dict por external_id con valores amigables.
    """
    out = {
        "item_id": item.get("item_id"),
        "title": item.get("title"),
    }
    # Solo copiar claves presentes y no-None
    for k in ("created_on", "last_event_on", "link", "app_item_id_formatted"):
        v = item.get(k, None)
        if v is not None:
            out[k] = v

    fields_out = {}

    def _coerce_int(x):
        if isinstance(x, int):
            return x
        if isinstance(x, str) and x.isdigit():
            return int(x)
        return None

    def resolve_external_id(field_obj):
        ext = field_obj.get("external_id")
        if isinstance(ext, str):
            return ext

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

        fid = field_obj.get("field_id")
        if isinstance(fid, dict):
            for k in ("field_id", "id", "value"):
                v = fid.get(k)
                fid_int = _coerce_int(v)
                if fid_int is not None:
                    return id_to_ext.get(fid_int)
            return None

        fid_int = _coerce_int(fid)
        if fid_int is not None:
            return id_to_ext.get(fid_int)

        return None

    for f in item.get("fields", []):
        ext = resolve_external_id(f)
        if not isinstance(ext, str) or not ext:
            continue

        ftype = f.get("type")
        values = f.get("values") or []
        meta = meta_by_ext.get(ext, {})

        def one(v):
            if ftype in ("text", "location", "calculation", "number"):
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

        # Si el resultado es None o queda vacío al podar, no se agrega
        cleaned = prune_nulls(result)
        if cleaned is not None and cleaned != {} and cleaned != []:
            fields_out[ext] = cleaned

    out["fields"] = fields_out
    # Podamos nulos de todo el objeto normalizado
    return prune_nulls(out)

def list_items(access_token, meta_by_ext, limit=200, offset=0, fetch_all=False, view_id=None):
    """
    Orquesta la paginación. Si fetch_all=True, recorre todas las páginas en bloques de 500.
    """
    if fetch_all:
        items = []
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

    return _fetch_items_page(access_token, limit=limit, offset=offset, view_id=view_id)

# ----------------- RUTAS PODIO -----------------
@app.route("/podio/fields", methods=["GET"])
def podio_fields():
    """
    Devuelve el mapeo: label -> external_id, y meta por external_id (tipo, opciones categoría).
    """
    try:
        token = get_app_token()
        _, maps = get_app_fields(token)
        # (Meta no suele traer nulls relevantes, pero por consistencia:)
        return jsonify(prune_nulls(maps)), 200
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

        # --- formato raw (igual que antes) ---
        if fmt == "raw":
            cleaned_raw = [prune_nulls(it) for it in raw_items]
            return jsonify({"count": len(cleaned_raw), "items": cleaned_raw}), 200

        # --- formato normalized (igual que antes) ---
        if fmt == "normalized":
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

        # --- nuevo formato: extracted ---
        if fmt in ("extracted", "extract", "raw-extracted"):
            def find_field(item, *, label=None, external_id=None):
                for f in item.get("fields", []):
                    if label is not None and f.get("label") == label:
                        return f
                    if external_id is not None and f.get("external_id") == external_id:
                        return f
                return None

            def value_from_field(field):
                """Valor 'humano' según tipo."""
                if not field or not field.get("values"):
                    return None

                vals = field["values"]

                def one(v, ftype):
                    if ftype in ("text", "location", "calculation", "number"):
                        return v.get("value")
                    if ftype == "category":
                        vv = v.get("value")
                        if isinstance(vv, dict):
                            return vv.get("text")
                        return vv
                    if ftype == "date":
                        return v.get("start_date") or v.get("start")
                    if ftype in ("app", "contact"):
                        return v.get("value")
                    return v.get("value", v)

                ftype = field.get("type")
                if len(vals) == 1:
                    return one(vals[0], ftype)
                return [one(v, ftype) for v in vals]

            extracted_items = []
            for item in raw_items:
                # Helper con fallback por label/external_id
                get = lambda lbl=None, ext=None: value_from_field(
                    find_field(item, label=lbl, external_id=ext)
                )

                # ------- Client: (app_item_id, title) -------
                client_val = get(lbl="Client", ext="relationship")
                def client_tuple(val):
                    if isinstance(val, dict):
                        return (val.get("app_item_id"), val.get("title"))
                    if isinstance(val, list):
                        t = []
                        for obj in val:
                            if isinstance(obj, dict):
                                t.append((obj.get("app_item_id"), obj.get("title")))
                        return t or None
                    return None
                client_pair = client_tuple(client_val)
                # Por compatibilidad, ID_Cliente sigue siendo solo el id (si es único)
                if isinstance(client_pair, tuple):
                    id_cliente = client_pair[0]
                elif isinstance(client_pair, list) and client_pair:
                    id_cliente = client_pair[0][0]
                else:
                    id_cliente = None

                # ------- Acc Rep Selling: (app_item_id, created_by.name) -------
                acc_val = get(lbl="Acc Rep Selling", ext="relation-rep")
                def acc_rep_pairs(val):
                    if isinstance(val, dict):
                        name = (val.get("created_by") or {}).get("name")
                        return (val.get("app_item_id"), name)
                    if isinstance(val, list):
                        pairs = []
                        for obj in val:
                            if isinstance(obj, dict):
                                name = (obj.get("created_by") or {}).get("name")
                                pairs.append((obj.get("app_item_id"), name))
                        return pairs or None
                    return None
                acc_pairs = acc_rep_pairs(acc_val)

                # Construcción del extract
                res = {
                    "app_item_id_formatted": item.get("app_item_id_formatted"),
                    "Project Name": get(lbl="Project Name", ext="project-name-2"),
                    "Project Location": get(lbl="Project Location", ext="project-location"),
                    "Job Status": get(lbl="Job Status", ext="job-status"),
                    "PO/WTN/WO# (QID)": (
                        get(lbl="Segment QID", ext="segment-id") or item.get("app_item_id_formatted")
                    ),
                    "Service Type": get(lbl="Service Type", ext="service-type"),
                    "Date Assigned": get(lbl="Date Assigned", ext="date-received"),
                    "Estimated Start Date": get(lbl="Estimated Start Date"),
                    "Estimated project duration": get(lbl="Estimated project duration"),
                    "GQM (Formula) Pricing": get(lbl="GQM (Formula) Pricing", ext="gqm-formula-total-cost"),
                    "GQM (Adj Formula) Pricing": get(lbl="GQM (Adj Formula) Pricing", ext="gqm-adj-formula-pricing"),
                    "GQM (Target) Sold Pricing": get(lbl="GQM (Target) Sold Pricing"),
                    "GQM (Premium in $)": get(lbl="2025 GQM (Premium in $)", ext="gqm-pricing-return-premium-in"),
                    "GQM (Final Sold) Pricing": get(lbl="GQM (Final Sold) Pricing", ext="gqm-final-pricing"),
                    "GQM (Final) %": get(lbl="GQM (Final) %"),  # si existe en el App
                    "GQM Total Change Orders": get(lbl="GQM Total Change Orders ", ext="total-change-orders"),
                    "initial_revision.created_by.user_id": (
                        item.get("initial_revision", {}).get("created_by", {}).get("user_id")
                    ),
                    "ID_Cliente": id_cliente,
                    "Client (app_item_id, title)": client_pair,
                    "Acc Rep Selling (app_item_id, name)": acc_pairs,
                }

                extracted_items.append(prune_nulls(res))

            return jsonify({
                "count": len(extracted_items),
                "items": extracted_items,
                "view_id": view_id,
                "fetch_all": fetch_all,
                "format": "extracted"
            }), 200

        # fallback: normalized
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
    Crea un ítem de prueba.
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
        return jsonify(prune_nulls(created)), 201
    except PodioError as e:
        return jsonify({"error": str(e)}), 502

@app.route("/podio/items", methods=["POST"])
def podio_create_item_custom():
    """
    Crea un ítem con los "fields" EXACTOS que envíes.
    """
    try:
        body = request.get_json(force=True)
        fields_payload = body.get("fields")
        if not isinstance(fields_payload, dict) or not fields_payload:
            return jsonify({"error": "Body debe incluir 'fields' (dict) con al menos un campo."}), 400

        token = get_app_token()
        external_id = body.get("external_id")
        created = create_item(token, fields_payload, external_id=external_id)
        return jsonify(prune_nulls(created)), 201
    except PodioError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"Body inválido: {str(e)}"}), 400

# ----------------- MAIN -----------------
if __name__=='__main__':
    app.run(debug=True)

