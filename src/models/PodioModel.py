import datetime as dt
import requests
from typing import Tuple, Dict, Any, List, Optional

from src.config import BASE_URL, TOKEN_URL, PODIO_APP_ID, PODIO_APP_TOKEN, PODIO_CLIENT_ID, PODIO_CLIENT_SECRET
from ..utils.common import PodioError#, prune_nulls


class PodioModel:
    # ========= AUTENTICACIÓN =========
    @classmethod
    def get_app_token(cls) -> str:
        """App Auth: obtiene access_token con grant_type=app."""
        try:
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
        except requests.HTTPError as e:
            raise PodioError(f"Error autenticando con Podio: {e.response.text}") from e

    # ========= METADATOS DEL APP =========
    @classmethod
    def get_app_fields(cls, access_token: str) -> Tuple[List[dict], Dict[str, Any]]:
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

    # ========= PAYLOAD DEMO =========
    @classmethod
    def build_demo_fields_payload(cls, meta_by_ext: Dict[str, Any]) -> Dict[str, Any]:
        """Arma un payload de ejemplo en base a los PRIMEROS campos disponibles por tipo."""
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

    # ========= CREACIÓN DE ÍTEM =========
    @classmethod
    def create_item(cls, access_token: str, fields_payload: Dict[str, Any], external_id: Optional[str] = None,
                    hook: bool = True, silent: bool = False) -> Dict[str, Any]:
        """Crea un ítem en el App con los campos proporcionados."""
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

    # ========= LISTADO (PAGINADO) =========
    @classmethod
    def _fetch_items_page(cls, access_token: str, limit: int = 100, offset: int = 0, view_id: Optional[str] = None) -> List[dict]:
        """Trae una página de ítems del App usando el endpoint de filtros."""
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

    @classmethod
    def list_items(cls, access_token: str, meta_by_ext: Dict[str, Any], limit: int = 200, offset: int = 0,
                   fetch_all: bool = False, view_id: Optional[str] = None) -> List[dict]:
        """Orquesta la paginación. Si fetch_all=True, recorre todas las páginas en bloques de 500."""
        if fetch_all:
            items = []
            page = 0
            while True:
                page_items = cls._fetch_items_page(access_token, limit=500, offset=page * 500, view_id=view_id)
                if not page_items:
                    break
                items.extend(page_items)
                if len(page_items) < 500:
                    break
                page += 1
            return items

        return cls._fetch_items_page(access_token, limit=limit, offset=offset, view_id=view_id)

    # ========= NORMALIZACIÓN =========
    @staticmethod
    def _normalize_item(item: dict, meta_by_ext: dict, id_to_ext: dict, category_mode: str = "both") -> dict:
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

            # 👉 ahora SIEMPRE incluimos la clave, aunque result sea None
            fields_out[ext] = result

        out["fields"] = fields_out
        return out

    