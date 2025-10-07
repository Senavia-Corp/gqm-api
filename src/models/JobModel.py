#======================================================= Código para la Base de Datos en Postgresql =================================
from sqlalchemy.dialects.postgresql import NUMERIC
from ..database.db import db

class JobORM(db.Model):
    """
    Modelo ORM para la tabla 'job' en Postgres.
    Ajusta tipos/longitudes si tu DDL real difiere.
    """
    __tablename__ = "job"

    id_job = db.Column(db.String(64), primary_key=True)

    project_name = db.Column(db.String(255), nullable=True)
    project_location = db.Column(db.String(255), nullable=True)
    job_status = db.Column(db.String(100), nullable=True)
    po_wtn_wo = db.Column(db.String(100), nullable=True)
    service_type = db.Column(db.String(100), nullable=True)

    # Si en tu BD es DATE/ TIMESTAMP, puedes cambiar este String por Date / DateTime.
    # Lo dejo String para evitar incompatibilidades si hoy lo guardas como texto.
    date_assigned = db.Column(db.String(50), nullable=True)

    # Campos numéricos de costos/porcentajes
    gqm_formula_pricing       = db.Column(NUMERIC(18, 2), nullable=True)
    gqm_adj_formula_pricing   = db.Column(NUMERIC(18, 2), nullable=True)
    gqm_target_sold_pricing   = db.Column(NUMERIC(18, 2), nullable=True)
    gqm_premium_in_money      = db.Column(NUMERIC(18, 2), nullable=True)
    gqm_final_sold_pricing    = db.Column(NUMERIC(18, 2), nullable=True)
    gqm_final_percentage      = db.Column(NUMERIC(7, 4),  nullable=True)  # ajusta si quieres 5,2 u otro
    gqm_total_change_orders   = db.Column(NUMERIC(18, 2), nullable=True)

    id_member = db.Column(db.String(64), nullable=True)
    id_client = db.Column(db.String(64), nullable=True)

    def to_dict(self):
        """
        Serializa con nombres "limpios" (coinciden con tus JSON actuales).
        Convierte Decimal a float para campos NUMERIC.
        """
        return {
            "id_job": self.id_job,
            "project_name": self.project_name,
            "project_location": self.project_location,
            "job_status": self.job_status,
            "po_wtn_wo": self.po_wtn_wo,
            "service_type": self.service_type,
            "date_assigned": self.date_assigned,
            "gqm_formula_pricing": float(self.gqm_formula_pricing) if self.gqm_formula_pricing is not None else None,
            "gqm_adj_formula_pricing": float(self.gqm_adj_formula_pricing) if self.gqm_adj_formula_pricing is not None else None,
            "gqm_target_sold_pricing": float(self.gqm_target_sold_pricing) if self.gqm_target_sold_pricing is not None else None,
            "gqm_premium_in_money": float(self.gqm_premium_in_money) if self.gqm_premium_in_money is not None else None,
            "gqm_final_sold_pricing": float(self.gqm_final_sold_pricing) if self.gqm_final_sold_pricing is not None else None,
            "gqm_final_percentage": float(self.gqm_final_percentage) if self.gqm_final_percentage is not None else None,
            "gqm_total_change_orders": float(self.gqm_total_change_orders) if self.gqm_total_change_orders is not None else None,
            "id_member": self.id_member,
            "id_client": self.id_client,
        }


#====================================================== Código de para la conexión y manejo de Podio =================================
import requests
from src.config import (
    BASE_URL, TOKEN_URL, PODIO_CLIENT_ID, PODIO_CLIENT_SECRET,
    PODIO_APP_ID, PODIO_APP_TOKEN
)

# ============ HELPER: token App 'Jobs' ============
def _jobs_get_app_token() -> str:
    """
    Autenticación App para el App 'Jobs' en Podio.
    Usa PODIO_APP_ID + PODIO_APP_TOKEN del .env.
    """
    if not PODIO_APP_ID or not PODIO_APP_TOKEN:
        raise RuntimeError("Faltan PODIO_APP_ID / PODIO_APP_TOKEN en .env")

    payload = {
        "grant_type": "app",
        "app_id": int(PODIO_APP_ID),
        "app_token": PODIO_APP_TOKEN,
        "client_id": PODIO_CLIENT_ID,
        "client_secret": PODIO_CLIENT_SECRET,
        "redirect_uri": "https://example.com/callback",
    }
    r = requests.post(TOKEN_URL, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]

# ============ HELPER: metadatos de campos ============
def _jobs_get_app_fields(access_token: str):
    """
    Devuelve (fields, maps) para el App 'Jobs'.
    maps: { ext_by_label, meta_by_ext, id_to_ext }
    """
    url = f"{BASE_URL}/app/{int(PODIO_APP_ID)}"
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

# ============ HELPER: fetch items (paginado) ============
def _jobs_fetch_items_page(access_token: str, *, limit=100, offset=0, view_id=None):
    """
    Trae una página de ítems del App 'Jobs'.
    """
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    if view_id:
        url = f"{BASE_URL}/item/app/{int(PODIO_APP_ID)}/filter/{int(view_id)}/"
        body = {"limit": limit, "offset": offset}
    else:
        url = f"{BASE_URL}/item/app/{int(PODIO_APP_ID)}/filter/"
        body = {"limit": limit, "offset": offset, "filters": {}}

    r = requests.post(url, json=body, headers=headers, timeout=40)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []

def _jobs_list_items(access_token: str, meta_by_ext: dict, *, limit=200, offset=0, fetch_all=False, view_id=None):
    """
    Orquesta la paginación para 'Jobs'.
    """
    if fetch_all:
        items, page = [], 0
        while True:
            pg = _jobs_fetch_items_page(access_token, limit=500, offset=page*500, view_id=view_id)
            if not pg:
                break
            items.extend(pg)
            if len(pg) < 500:
                break
            page += 1
        return items
    return _jobs_fetch_items_page(access_token, limit=limit, offset=offset, view_id=view_id)

# ============ NORMALIZACIÓN (copia local, sin prune) ============ PROBABLEMENTE NO MIRAR ESTO :D
def _jobs_normalize_item(item: dict, meta_by_ext: dict, id_to_ext: dict, *, category_mode="both") -> dict:
    """
    Convierte item["fields"] (lista) en dict por external_id con valores amigables.
    """
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

# ============ API pública Podio: GET (raw|normalized|extracted) ============
def podio_list_jobs(*, limit=200, offset=0, fetch_all=False, view_id=None, fmt="normalized", category_mode="both"):
    """
    Devuelve items del App 'Jobs' de Podio en formato:
      - raw | normalized | extracted
    """
    token = _jobs_get_app_token()
    _, maps = _jobs_get_app_fields(token)

    raw_items = _jobs_list_items(
        token, maps["meta_by_ext"], limit=limit, offset=offset, fetch_all=fetch_all, view_id=view_id
    )

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
            _jobs_normalize_item(it, maps["meta_by_ext"], maps["id_to_ext"], category_mode=category_mode)
            for it in raw_items
        ]
        return {
            "count": len(normalized),
            "items": normalized,
            "view_id": view_id,
            "fetch_all": fetch_all,
            "format": "normalized",
        }

    # ---- extracted: los campos más usados de tu App 'Jobs'
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

    extracted_items = []
    for item in raw_items:
        get = lambda lbl=None, ext=None: value_from_field(find_field(item, label=lbl, external_id=ext))

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
            "GQM (Final) %": get(lbl="GQM (Final) %"),
            "GQM Total Change Orders": get(lbl="GQM Total Change Orders ", ext="total-change-orders"),
            "initial_revision.created_by.user_id": (
                item.get("initial_revision", {}).get("created_by", {}).get("user_id")
            ),
            "ID_Cliente": id_cliente,
            "Client (app_item_id, title)": client_pair,
            "Acc Rep Selling (app_item_id, name)": acc_pairs,
        }
        extracted_items.append(res)

    return {
        "count": len(extracted_items),
        "items": extracted_items,
        "view_id": view_id,
        "fetch_all": fetch_all,
        "format": "extracted",
    }

# ============ API pública Podio: POST / PATCH / DELETE ============
def podio_create_job_item(*, fields_payload: dict, external_id: str | None = None, hook: bool = True, silent: bool = False) -> dict:
    """
    Crea un ítem en el App 'Jobs' de Podio.
    """
    token = _jobs_get_app_token()
    url = f"{BASE_URL}/item/app/{int(PODIO_APP_ID)}/"
    body = {"fields": fields_payload}
    if external_id:
        body["external_id"] = external_id

    params = {"hook": str(hook).lower(), "silent": str(silent).lower()}
    r = requests.post(
        url, params=params, json=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def podio_update_job_item(*, item_id: int, fields_payload: dict, hook: bool = True, silent: bool = False) -> dict:
    """
    Actualiza campos de un ítem del App 'Jobs' en Podio.
    Nota: Podio usa PUT /item/{item_id} para actualizar.
    """
    token = _jobs_get_app_token()
    url = f"{BASE_URL}/item/{int(item_id)}"
    body = {"fields": fields_payload}
    params = {"hook": str(hook).lower(), "silent": str(silent).lower()}

    r = requests.put(
        url, params=params, json=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def podio_delete_job_item(*, item_id: int) -> None:
    """
    Elimina un ítem del App 'Jobs' en Podio.
    """
    token = _jobs_get_app_token()
    url = f"{BASE_URL}/item/{int(item_id)}"
    r = requests.delete(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=20
    )
    r.raise_for_status()
    return None
