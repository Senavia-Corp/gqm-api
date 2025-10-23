#========================== Código para la Base de Datos en Postgresql =================================
from ..database.db import db

class ClientORM(db.Model):
    """
    Modelo ORM para la tabla Client.
    - __tablename__: nombre de la tabla en Postgres. 
    """
    __tablename__ = "client" 

    # Atributo Python -> Columna real en Postgres
    id_client = db.Column("ID_Client", db.String(64), primary_key=True)  # PK texto

    # Columna real con espacio y slash. SQLAlchemy la citará; 
    # en el código accedes como .client_community
    client_community = db.Column("Client/Comunity", db.String(255), nullable=True)

    parent_mgmt_company = db.Column("Parent Mgmt Company", db.String(255), nullable=True)

    def to_dict(self):
        """
        Serializa con los nombres de ATRIBUTOS Python (limpios).
        Si prefieres los nombres EXACTOS de las columnas, cámbialo.
        """
        return {
            "id_client": self.id_client,
            "client_community": self.client_community,
            "parent_mgmt_company": self.parent_mgmt_company,
        }

#========================== Código de para la conexión y manejo de Podio =================================
import requests
from src.config import (
    BASE_URL, TOKEN_URL, PODIO_CLIENT_ID, PODIO_CLIENT_SECRET,
    PODIO_CLIENTS_APP_ID, PODIO_CLIENTS_APP_TOKEN
)

# ============ HELPER: token App 'Clients' ============
def _clients_get_app_token() -> str:
    """
    Autenticación App para el App 'Clients' en Podio.
    Usa PODIO_CLIENTS_APP_ID + PODIO_CLIENTS_APP_TOKEN del .env.
    """
    if not PODIO_CLIENTS_APP_ID or not PODIO_CLIENTS_APP_TOKEN:
        raise RuntimeError("Faltan PODIO_CLIENTS_APP_ID / PODIO_CLIENTS_APP_TOKEN en .env")

    payload = {
        "grant_type": "app",
        "app_id": int(PODIO_CLIENTS_APP_ID),
        "app_token": PODIO_CLIENTS_APP_TOKEN,
        "client_id": PODIO_CLIENT_ID,
        "client_secret": PODIO_CLIENT_SECRET,
        "redirect_uri": "https://example.com/callback",
    }
    r = requests.post(TOKEN_URL, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]

# ============ HELPER: metadatos de campos ============
def _clients_get_app_fields(access_token: str):
    """
    Devuelve (fields, maps) para el App 'Clients'.
    maps: { ext_by_label, meta_by_ext, id_to_ext }
    """
    url = f"{BASE_URL}/app/{int(PODIO_CLIENTS_APP_ID)}"
    r = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    r.raise_for_status()
    app_json = r.json()

    ext_by_label, meta_by_ext, id_to_ext = {}, {}, {}
    for f in app_json.get("fields", []):
        ext = f.get("external_id")
        ftype = f.get("type")
        fid = f.get("field_id")
        label = (f.get("config", {}) or {}).get("label", "")
        label_key = label.strip().lower().replace(" ", "_")

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

# ============ HELPER: fetch items (paginado) ============
def _clients_fetch_items_page(access_token: str, *, limit=100, offset=0, view_id=None):
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    if view_id:
        url = f"{BASE_URL}/item/app/{int(PODIO_CLIENTS_APP_ID)}/filter/{int(view_id)}/"
        body = {"limit": limit, "offset": offset}
    else:
        url = f"{BASE_URL}/item/app/{int(PODIO_CLIENTS_APP_ID)}/filter/"
        body = {"limit": limit, "offset": offset, "filters": {}}

    r = requests.post(url, json=body, headers=headers, timeout=40)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []

def _clients_list_items(access_token: str, meta_by_ext: dict, *, limit=200, offset=0, fetch_all=False, view_id=None):
    if fetch_all:
        items, page = [], 0
        while True:
            pg = _clients_fetch_items_page(access_token, limit=500, offset=page*500, view_id=view_id)
            if not pg:
                break
            items.extend(pg)
            if len(pg) < 500:
                break
            page += 1
        return items
    return _clients_fetch_items_page(access_token, limit=limit, offset=offset, view_id=view_id)

# ============ NORMALIZACIÓN (copia local, sin prune) ============
def _clients_normalize_item(item: dict, meta_by_ext: dict, id_to_ext: dict, *, category_mode="both") -> dict:
    out = {
        "item_id": item.get("item_id"),
        "title": item.get("title"),
        "created_on": item.get("created_on"),
        "last_event_on": item.get("last_event_on"),
        "link": item.get("link"),
        "app_item_id_formatted": item.get("app_item_id_formatted"),
    }

    fields_out = {}

    def _coerce_int(x):
        if isinstance(x, int): return x
        if isinstance(x, str) and x.isdigit(): return int(x)
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

        fields_out[ext] = result

    out["fields"] = fields_out
    return out

# ============ API pública para routes/Client.py ============
def podio_list_clients(*, limit=200, offset=0, fetch_all=False, view_id=None, fmt="normalized", category_mode="both"):
    """
    Devuelve items del App 'Clients' de Podio:
      - format=raw|normalized|extracted
    """
    token = _clients_get_app_token()
    _, maps = _clients_get_app_fields(token)

    raw_items = _clients_list_items(token, maps["meta_by_ext"], limit=limit, offset=offset,
                                    fetch_all=fetch_all, view_id=view_id)

    if fmt == "raw":
        return {
            "count": len(raw_items),
            "items": raw_items,
            "view_id": view_id,
            "fetch_all": fetch_all,
            "format": "raw",
        }

    if fmt == "normalized":
        normalized = [
            _clients_normalize_item(it, maps["meta_by_ext"], maps["id_to_ext"], category_mode=category_mode)
            for it in raw_items
        ]
        return {
            "count": len(normalized),
            "items": normalized,
            "view_id": view_id,
            "fetch_all": fetch_all,
            "format": "normalized",
        }

    # ---- extracted: solo campos de interés
    def find_field(item, *, label=None, external_id=None):
        for f in item.get("fields", []):
            if label is not None and f.get("label") == label:
                return f
            if external_id is not None and f.get("external_id") == external_id:
                return f
        return None

    def value_from_field(field):
        if not field or not field.get("values"): return None
        vals, ftype = field["values"], field.get("type")
        def one(v):
            if ftype in ("text", "location", "calculation", "number"):
                return v.get("value")
            if ftype == "category":
                vv = v.get("value")
                return vv.get("text") if isinstance(vv, dict) else vv
            if ftype == "date":
                return v.get("start_date") or v.get("start")
            if ftype in ("app", "contact"):
                return v.get("value")
            return v.get("value", v)
        return one(vals[0]) if len(vals) == 1 else [one(v) for v in vals]

    extracted = []
    for item in raw_items:
        get = lambda lbl=None, ext=None: value_from_field(find_field(item, label=lbl, external_id=ext))
        extracted.append({
            "app_item_id_formatted": item.get("app_item_id_formatted"),
            "id_client": get(lbl="ID_Client"),
            "client_community": get(lbl="Client/Comunity"),
            "parent_mgmt_company": get(lbl="Parent Mgmt Company"),
        })

    return {
        "count": len(extracted),
        "items": extracted,
        "view_id": view_id,
        "fetch_all": fetch_all,
        "format": "extracted",
    }
