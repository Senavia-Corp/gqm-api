from src.config import TAS_TAP_APP_ID
from .podio_base_services import PodioBaseService


class PodioTasksRouter:

    def __init__(self):
        self.service = PodioBaseService("TASK", TAS_TAP_APP_ID)

    def get_service(self) -> PodioBaseService:
        """
        Retorna el service de Podio para Tasks.
        """
        return self.service


# Instancia global del router (para usar en servicios o rutas)
podio_tasks_router = PodioTasksRouter()
