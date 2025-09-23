import os
import json
import datetime as dt
from flask import Flask,  request
import requests
from dotenv import load_dotenv
from main import get_app_token, get_app_fields, list_items,_normalize_item

# ======== Carga .env ========
load_dotenv()

# ======== Config Podio ========
BASE_URL = "https://api.podio.com"
TOKEN_URL = "https://api.podio.com/oauth/token/v2"

PODIO_CLIENT_ID = os.getenv("PODIO_CLIENT_ID")
PODIO_CLIENT_SECRET = os.getenv("PODIO_CLIENT_SECRET")
PODIO_APP_ID = os.getenv("PODIO_APP_ID")
PODIO_APP_TOKEN = os.getenv("PODIO_APP_TOKEN")

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
        print("meta_by_ext: ", meta_by_ext[0][0])
        item = [i for i in meta_by_ext[1].items()]
        exti , metai = item[0]
        print(f"exti: {exti}\n\n metai: {metai.keys()}")

        for ext, meta in meta_by_ext[1].items():
            
            if meta["type"] == ftype:
                return ext, meta
               
        return None, None

    # TEXT
    ext, meta = first_field_of("text")
    # print(f"ext: {ext}, meta: {meta}")
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

token = get_app_token()
meta_by_ext = get_app_fields(token)
test_1 = build_demo_fields_payload(meta_by_ext)
print(test_1)


