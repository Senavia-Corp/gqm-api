from src.config import CLI_TAP_APP_ID
from .podio_base_services import PodioBaseService


class PodioClientsRouter:

    def __init__(self):
        self.service = PodioBaseService("CLI", CLI_TAP_APP_ID)

    def get_service(self) -> PodioBaseService:
        """
        Retorna el service de Podio para Client.
        """
        return self.service


# Instancia global del router (para usar en servicios o rutas)
podio_clients_router = PodioClientsRouter()
