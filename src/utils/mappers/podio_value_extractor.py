from .mapper_aux_functions import clean_html, has_html


def get_podio_field_value(fields: list, field_id: str):
    for f in fields:
        if f.get("external_id") == field_id or f.get("label") == field_id:
            raw = f.get("values") or f.get("value")

            # ----------------------------
            # LISTA DE VALORES (lo más común en Podio)
            # ----------------------------
            if isinstance(raw, list) and raw:
                values = []
                has_html_content = False

                for item in raw:
                    # EMBED (website, links, etc)
                    if isinstance(item, dict) and "embed" in item:
                        embed = item["embed"]
                        return (
                            embed.get("original_url")
                            or embed.get("resolved_url")
                            or embed.get("url")
                        )

                    val = item.get("value", item)

                    # Category
                    if isinstance(val, dict) and "text" in val:
                        values.append(clean_html(val["text"]))
                        has_html_content = has_html_content or has_html(
                            val["text"])

                    # {"value": "..."}
                    elif isinstance(val, dict) and "value" in val:
                        values.append(clean_html(val["value"]))
                        has_html_content = has_html_content or has_html(
                            val["value"])

                    # string directo (phones, emails)
                    elif isinstance(val, str):
                        values.append(clean_html(val))
                        has_html_content = has_html_content or has_html(val)

                if not values:
                    return None

                # 🔑 Decisión automática
                # - Texto con HTML → string con saltos
                # - Phones / Emails → array
                if len(values) > 1:
                    return "\n".join(values) if has_html_content else values

                return values[0]

            # ----------------------------
            # EMBED directo (fallback)
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
