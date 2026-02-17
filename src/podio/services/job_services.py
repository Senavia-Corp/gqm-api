
from src.config import get_job_app_credentials
from .podio_base_services import PodioBaseService


class PodioJobsRouter:
    """
    Router inteligente para Jobs dinámicos (QID / PTL / PAR por año)
    """

    def get_service(self, job_type: str, year: int) -> PodioBaseService:
        if not job_type:
            raise ValueError("job_type está vacío o es None")

        if year is None:
            raise ValueError("year es obligatorio para Jobs")

        job_type = job_type.upper().strip()

        # 🔑 Aquí se decide TODO
        app_creds = get_job_app_credentials(year, job_type)
        app_id = app_creds["APP_ID"]

        return PodioBaseService(
            app_type=job_type,
            app_id=app_id,
            year=year
        )


# Instancia global del router (para usar en servicios o rutas)
podio_jobs_router = PodioJobsRouter()
