from ..services.jobs_service import build_job_data

def get_job_by_id(job_id: str, query: str | None = None) -> dict:
    # Aquí podrías hacer validaciones, normalizar inputs, etc.
    job = build_job_data(job_id)
    if query:
        job["query"] = query
    return job
