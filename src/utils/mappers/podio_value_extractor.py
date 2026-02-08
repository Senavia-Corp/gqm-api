from .mapper_aux_functions import clean_html, has_html


def get_podio_field_value(fields: list, field_ids):

    if not field_ids:
        return None

    # Normalizar a lista
    if isinstance(field_ids, str):
        field_ids = [field_ids]

    field_ids = {fid.lower() for fid in field_ids}

    for f in fields:
        external_id = f.get("external_id")
        label = f.get("label")

        if (
            (external_id and external_id.lower() in field_ids)
            or (label and label.lower() in field_ids)
        ):
            raw = f.get("values") or f.get("value")

            # ----------------------------
            # Dates
            # ----------------------------
            if f.get("type") == "date" and isinstance(raw, list) and raw:
                date_obj = raw[0]
                return (
                    date_obj.get("start_date")
                    or date_obj.get("start")
                    or date_obj.get("end_date")
                    or date_obj.get("end")
                )

            # ----------------------------
            # TAGS
            # ----------------------------
            if f.get("type") == "tag" and isinstance(raw, list):
                return [
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
                        return (
                            embed.get("original_url")
                            or embed.get("resolved_url")
                            or embed.get("url")
                        )

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

                if not values:
                    return None

                if len(values) > 1:
                    return "\n".join(values) if has_html_content else values

                return values[0]

            # ----------------------------
            # Embed (URLs)
            # ----------------------------
            if isinstance(raw, dict) and "embed" in raw:
                embed = raw["embed"]
                return (
                    embed.get("original_url")
                    or embed.get("resolved_url")
                    or embed.get("url")
                )

            # ----------------------------
            # Category single
            # ----------------------------
            if isinstance(raw, dict) and "text" in raw:
                return clean_html(raw["text"])

            # ----------------------------
            # {"value": "..."}
            # ----------------------------
            if isinstance(raw, dict) and "value" in raw:
                return clean_html(raw["value"])

            # ----------------------------
            # string directo
            # ----------------------------
            if isinstance(raw, str):
                return clean_html(raw)

    return None
