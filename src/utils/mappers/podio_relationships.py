from sqlmodel import select

# Obtener las relaciones tipo app


def get_related_app_ids(
    fields: list,
    external_id: str,
    session,
    model,
    podio_field: str,
    internal_id_field: str
) -> list:
    """
    Devuelve una lista de IDs internos del modelo relacionado
    a partir de un campo app de Podio.
    """
    results = []

    for f in fields:
        if f.get("external_id") != external_id:
            continue

        vals = f.get("values", [])
        if not vals or not session:
            return []

        for v in vals:
            podio_item_id = v.get("value", {}).get("item_id")
            if not podio_item_id:
                continue

            obj = session.exec(
                select(model).where(
                    getattr(model, podio_field) == str(podio_item_id)
                )
            ).first()

            if obj:
                results.append(getattr(obj, internal_id_field))

        return results  # solo hay un field por external_id

    return []


# Obtener las relaciones tipo contact
def get_contact_profile_ids(
    fields: list,
    external_id: str
) -> list[str]:
    """
    Devuelve una lista de profile_id desde un campo contact de Podio.
    """
    for f in fields:
        if f.get("external_id") != external_id:
            continue

        vals = f.get("values", [])
        return [
            str(v.get("value", {}).get("profile_id"))
            for v in vals
            if v.get("value", {}).get("profile_id")
        ]

    return []


# Obtener textos por external_id
def get_text_values_by_external_id(
    fields: list,
    external_id: str
) -> list[str]:
    """
    Devuelve una lista de strings desde un campo text de Podio.
    """
    for f in fields:
        if f.get("external_id") == external_id:
            return [
                v.get("value")
                for v in f.get("values", [])
                if v.get("value")
            ]
    return []
