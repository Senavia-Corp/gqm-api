
from src.config import get_job_app_credentials
from .podio_base_services import PodioBaseService, PodioReadOnlyService


class PodioJobsRouter:
    """
    Router inteligente para Jobs dinámicos (QID / PTL / PAR por año)
    """

    def get_service(self, job_type: str, year: int,
                    solo_lectura: bool = False) -> PodioBaseService:
        if not job_type:
            raise ValueError("job_type está vacío o es None")

        if year is None:
            raise ValueError("year es obligatorio para Jobs")

        job_type = job_type.upper().strip()

        # 🔑 Aquí se decide TODO
        app_creds = get_job_app_credentials(year, job_type)
        app_id = app_creds["APP_ID"]

        clase = PodioReadOnlyService if solo_lectura else PodioBaseService
        return clase(
            app_type=job_type,
            app_id=app_id,
            year=year
        )

    def get_readonly_service(self, job_type: str, year: int) -> PodioReadOnlyService:
        """Para censo de paridad e importación: no puede escribir ni por error."""
        return self.get_service(job_type, year, solo_lectura=True)


# Instancia global del router (para usar en servicios o rutas)
podio_jobs_router = PodioJobsRouter()
