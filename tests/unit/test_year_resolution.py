"""REG-015: el año de la app Podio se persiste y no se adivina."""
from datetime import datetime

from src.models.JobModel import Job
from src.utils.podio_job_sync import resolve_job_app_year


def test_persisted_year_wins():
    job = Job(podio_app_year=2024, Date_assigned=datetime(2026, 8, 1))
    assert resolve_job_app_year(job) == 2024


def test_fallback_to_date_assigned():
    job = Job(Date_assigned=datetime(2023, 3, 5))
    assert resolve_job_app_year(job) == 2023


def test_no_year_resolvable_returns_none():
    # Nunca now(): sin dato, no se sincroniza (queda en PodioFailedSync).
    assert resolve_job_app_year(Job()) is None
