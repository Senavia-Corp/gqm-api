from .mapper_aux_functions import clean_html, has_html


def get_job_field_value(fields: list, field_cfg: dict):

    if not field_cfg:
        return None

    raw_field_ids = field_cfg.get("field_id", [])
    if isinstance(raw_field_ids, int):
        field_ids = {raw_field_ids}
    else:
        field_ids = set(raw_field_ids)

    # El orden de declaración de external_ids es la prioridad: cuando dos
    # campos de la app matchean aliases distintos del mismo BD-field
    # (colisión project-name-2 / project-name), gana el alias declarado
    # primero, no el orden de campos del item.
    ext_priority = {
        eid.lower(): idx
        for idx, eid in enumerate(field_cfg.get("external_ids", []))
    }

    is_multi = field_cfg.get("multi", False)

    results = []
    best_rank = None
    best_value = None

    for f in fields:
        f_id = f.get("field_id")
        f_ext = f.get("external_id")

        match_id = (f_id in field_ids) if field_ids else False
        match_ext = (f_ext and f_ext.lower() in ext_priority) if ext_priority else False

        if not (match_id or match_ext):
            continue

        raw = f.get("values") or f.get("value")

        value = None

        # ----------------------------
        # Dates
        # ----------------------------
        if f.get("type") == "date" and isinstance(raw, list) and raw:
            date_obj = raw[0]
            start = (
                date_obj.get("start_date")
                or date_obj.get("start")
            )
            end = (
                date_obj.get("end_date")
                or date_obj.get("end")
            )
            value = (start, end) if start else None

        # ----------------------------
        # TAGS
        # ----------------------------
        if f.get("type") == "tag" and isinstance(raw, list):
            value = [
                item.get("value")
                for item in raw
                if isinstance(item, dict) and item.get("value")
            ] or None

        # ----------------------------
        # Lista de valores
        # ----------------------------
        if isinstance(raw, list) and raw:
            values = []
            has_html_content = False

            for item in raw:
                # EMBED
                if isinstance(item, dict) and "embed" in item:
                    embed = item["embed"]
                    value = (
                        embed.get("original_url")
                        or embed.get("resolved_url")
                        or embed.get("url")
                    )
                    break

                val = item.get("value", item)

                if isinstance(val, dict) and "text" in val:
                    values.append(clean_html(val["text"]))
                    has_html_content |= has_html(val["text"])

                elif isinstance(val, dict) and "value" in val:
                    values.append(clean_html(val["value"]))
                    has_html_content |= has_html(val["value"])

                elif isinstance(val, str):
                    values.append(clean_html(val))
                    has_html_content |= has_html(val)

            if values:
                value = values if len(values) > 1 else values[0]

        # ----------------------------
        # Embed (URLs)
        # ----------------------------
        if isinstance(raw, dict) and "embed" in raw:
            embed = raw["embed"]
            value = (
                embed.get("original_url")
                or embed.get("resolved_url")
                or embed.get("url")
            )

        # ----------------------------
        # Category single
        # ----------------------------
        if isinstance(raw, dict) and "text" in raw:
            value = clean_html(raw["text"])

        # ----------------------------
        # {"value": "..."}
        # ----------------------------
        if isinstance(raw, dict) and "value" in raw:
            value = clean_html(raw["value"])

        # ----------------------------
        # string directo
        # ----------------------------
        if isinstance(raw, str):
            value = clean_html(raw)

        # ----------------------------
        # Salida
        # ----------------------------
        if value is None:
            continue

        # ----------------------------
        # Acumulación
        # ----------------------------
        if is_multi:
            results.append(value)
        else:
            # match por field_id (id exacto de la app-año) = máxima prioridad;
            # match por slug = prioridad según orden de declaración.
            rank = -1 if match_id else ext_priority[f_ext.lower()]
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_value = value

    if is_multi:
        return results or None

    return best_value
