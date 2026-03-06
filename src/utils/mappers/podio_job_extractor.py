from .mapper_aux_functions import clean_html, has_html


def get_job_field_value(fields: list, field_cfg: dict):

    if not field_cfg:
        return None

    raw_field_ids = field_cfg.get("field_id", [])
    if isinstance(raw_field_ids, int):
        field_ids = {raw_field_ids}
    else:
        field_ids = set(raw_field_ids)

    external_ids = {
        eid.lower() for eid in field_cfg.get("external_ids", [])
    }

    is_multi = field_cfg.get("multi", False)

    results = []

    for f in fields:
        f_id = f.get("field_id")
        f_ext = f.get("external_id")

        # Ambos deben coincidir
        if f_id not in field_ids:
            continue

        if not f_ext or f_ext.lower() not in external_ids:
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
            return value

    if is_multi:
        return results or None

    return None
