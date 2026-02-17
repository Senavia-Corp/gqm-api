from src.config import PODIO_BLDGDEPT_APP_ID
from .podio_base_services import PodioBaseService


class PodioBldgDeptRouter:

    def __init__(self):
        self.service = PodioBaseService("BDEP", PODIO_BLDGDEPT_APP_ID)

    def get_service(self) -> PodioBaseService:
        """
        Retorna el service de Podio para Building Department.
        """
        return self.service


# Instancia global del router (para usar en servicios o rutas)
podio_bldg_dept_router = PodioBldgDeptRouter()
