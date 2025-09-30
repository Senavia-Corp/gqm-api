from flask import Blueprint, jsonify, request
from ..utils.common import PodioError#, prune_nulls
from ..models.PodioModel import PodioModel

podio_bp = Blueprint("podio_blueprint", __name__, url_prefix="/podio")


@podio_bp.route("/fields", methods=["GET"])
def podio_fields():
    """Devuelve el mapeo: label -> external_id, y meta por external_id (tipo, opciones categoría)."""
    try:
        token = PodioModel.get_app_token()
        _, maps = PodioModel.get_app_fields(token)
        return jsonify(maps), 200
    except PodioError as e:
        return jsonify({"error": str(e)}), 502


@podio_bp.route("/items", methods=["GET"])
def podio_list_items():
    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
        fetch_all = str(request.args.get("all", "false")).lower() in ("1", "true", "yes")
        view_id = request.args.get("view_id")
        fmt = (request.args.get("format") or "normalized").lower()
        category_mode = (request.args.get("category_mode") or "both").lower()

        token = PodioModel.get_app_token()
        _, maps = PodioModel.get_app_fields(token)

        raw_items = PodioModel.list_items(
            token,
            maps["meta_by_ext"],
            limit=limit,
            offset=offset,
            fetch_all=fetch_all,
            view_id=view_id
        )

        if fmt == "raw":
            #Antes cuando omitia los valores nulos:
            #cleaned_raw = [prune_nulls(it) for it in raw_items]
            #return jsonify({"count": len(cleaned_raw), "items": cleaned_raw}), 200
            return jsonify({"count": len(raw_items), "items": raw_items}), 200

        if fmt == "normalized":
            normalized = [
                PodioModel._normalize_item(it, maps["meta_by_ext"], maps["id_to_ext"], category_mode=category_mode)
                for it in raw_items
            ]
            return jsonify({
                "count": len(normalized),
                "items": normalized,
                "view_id": view_id,
                "fetch_all": fetch_all
            }), 200

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
                #Antes cuando omitia los valores nulos:
                #extracted_items.append(prune_nulls(res))
                extracted_items.append(res)

            return jsonify({
                "count": len(extracted_items),
                "items": extracted_items,
                "view_id": view_id,
                "fetch_all": fetch_all,
                "format": "extracted"
            }), 200

        # fallback: normalized
        normalized = [
            PodioModel._normalize_item(it, maps["meta_by_ext"], maps["id_to_ext"], category_mode=category_mode)
            for it in raw_items
        ]
        return jsonify({
            "count": len(normalized),
            "items": normalized,
            "view_id": view_id,
            "fetch_all": fetch_all
        }), 200

    except request.HTTPError as e:
        return jsonify({"error": f"Podio API: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@podio_bp.route("/items/demo", methods=["POST"])
def podio_create_demo_item():
    """Crea un ítem de prueba."""
    try:
        body = request.get_json(silent=True) or {}
        token = PodioModel.get_app_token()
        _, maps = PodioModel.get_app_fields(token)

        fields_payload = body.get("fields") or PodioModel.build_demo_fields_payload(maps["meta_by_ext"])
        external_id = body.get("external_id")
        hook = bool(body.get("hook", True))
        silent = bool(body.get("silent", False))

        created = PodioModel.create_item(token, fields_payload, external_id=external_id, hook=hook, silent=silent)
        return jsonify(created), 201 #jsonify(prune_nulls(created)), 201 ##Antes cuando omitia los valores nulos
    except PodioError as e:
        return jsonify({"error": str(e)}), 502


@podio_bp.route("/items", methods=["POST"])
def podio_create_item_custom():
    """Crea un ítem con los 'fields' EXACTOS que envíes."""
    try:
        body = request.get_json(force=True)
        fields_payload = body.get("fields")
        if not isinstance(fields_payload, dict) or not fields_payload:
            return jsonify({"error": "Body debe incluir 'fields' (dict) con al menos un campo."}), 400

        token = PodioModel.get_app_token()
        external_id = body.get("external_id")
        created = PodioModel.create_item(token, fields_payload, external_id=external_id)
        return jsonify(created), 201 #jsonify(prune_nulls(created)), 201 ##Antes cuando omitia los valores nulos
    except PodioError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"Body inválido: {str(e)}"}), 400
