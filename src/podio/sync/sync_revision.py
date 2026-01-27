from src.models.ClientModel import Client
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.utils.mappers.from_podio.client_mapper import map_podio_item_to_client
from src.utils.mappers.from_podio.parent_mgmt_co_mapper import map_podio_item_to_parent_mgmt_co

PODIO_SYNC_REGISTRY = {
    "client": {
        "model": Client,
        "mapper": map_podio_item_to_client,
        "endpoint": "/client",
        "app_type": "CLI"
    },
    "parent_mgmt_co": {
        "model": ParentMgmtCo,
        "mapper": map_podio_item_to_parent_mgmt_co,
        "endpoint": "/parent_mgmt_co",
        "app_type": "PMC"
    },
}
