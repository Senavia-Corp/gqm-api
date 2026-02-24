
from ..qbo_aux_functions import extract_value


def map_entity(qbo_obj: dict, field_map: dict):
    mapped = {}

    for db_field, qbo_path in field_map.items():

        # Si es lista, intenta en orden
        if isinstance(qbo_path, list):
            value = None
            for path in qbo_path:
                value = extract_value(qbo_obj, path)
                if value is not None:
                    break
            mapped[db_field] = value

        else:
            mapped[db_field] = extract_value(qbo_obj, qbo_path)

    return mapped
