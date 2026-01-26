import json
from src.utils.get_podio_items import get_podio_item

if __name__ == "__main__":
    ITEM_ID = 3235973637  # cambia por el que quieras

    item = get_podio_item(ITEM_ID)

    print(
        json.dumps(
            item,
            indent=2,
            ensure_ascii=False
        )
    )
