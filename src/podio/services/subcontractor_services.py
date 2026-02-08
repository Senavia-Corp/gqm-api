from src.config import PODIO_SUBCONTRACTOR_APP_ID
from .podio_base_services import PodioBaseService


class PodioSubcRouter:

    def __init__(self):
        self.service = PodioBaseService("SUBC", PODIO_SUBCONTRACTOR_APP_ID)

    def get_service(self) -> PodioBaseService:
        """
        Retorna el service de Podio para Subcontractor.
        """
        return self.service


# Instancia global del router (para usar en servicios o rutas)
podio_subc_router = PodioSubcRouter()
