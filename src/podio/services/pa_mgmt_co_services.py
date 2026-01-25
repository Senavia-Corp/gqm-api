from src.config import PODIO_PAMGMTCO_APP_ID
from .podio_base_services import PodioBaseService


class PodioPaMgmtCoRouter:

    def __init__(self):
        self.service = PodioBaseService("PMC", PODIO_PAMGMTCO_APP_ID)

    def get_service(self) -> PodioBaseService:
        """
        Retorna el service de Podio para Parent Mgmt Co.
        """
        return self.service


# Instancia global del router (para usar en servicios o rutas)
podio_pa_mgmt_co_router = PodioPaMgmtCoRouter()
