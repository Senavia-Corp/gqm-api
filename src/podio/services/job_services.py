
from src.config import (
    QID_TAP_APP_ID,
    PTL_TAP_APP_ID,
    PAR_TAP_APP_ID
)
from .podio_base_services import PodioBaseService


class PodioJobsRouter:
    """
    Router inteligente que selecciona el App de Podio correcto
    basado en el Job_type recibido (QID, PTL, PAR).
    """

    def __init__(self):
        # Mapeo: Job Type → Servicio de Podio correspondiente
        self.services = {
            "QID": PodioBaseService("QID", QID_TAP_APP_ID),
            "PTL": PodioBaseService("PTL", PTL_TAP_APP_ID),
            "PAR": PodioBaseService("PAR", PAR_TAP_APP_ID),
        }

    def get_service(self, job_type: str) -> PodioBaseService:
        """
        Retorna el service de Podio correcto según el Job_type.
        """
        if not job_type:
            raise ValueError("Job_type está vacío o es None.")

        job_type = job_type.upper().strip()

        if job_type not in self.services:
            raise ValueError(
                f"Tipo de trabajo '{job_type}' no es válido. "
                f"Tipos permitidos: {', '.join(self.services.keys())}"
            )

        return self.services[job_type]


# Instancia global del router (para usar en servicios o rutas)
podio_jobs_router = PodioJobsRouter()
