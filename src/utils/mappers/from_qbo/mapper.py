
from ..qbo_aux_functions import extract_value


def map_entity(qbo_obj: dict, field_map: dict):
    mapped = {}

    for db_field, qbo_path in field_map.items():
        mapped[db_field] = extract_value(qbo_obj, qbo_path)

    return mapped
