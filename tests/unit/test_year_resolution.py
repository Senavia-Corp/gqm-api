"""REG-015: el año de la app Podio se persiste y no se adivina."""
from datetime import datetime

from src.models.JobModel import Job
from src.utils.podio_job_sync import resolve_job_app_year


def test_persisted_year_wins():
    job = Job(podio_app_year=2024, Date_assigned=datetime(2026, 8, 1))
    assert resolve_job_app_year(job) == 2024


def test_ya_no_se_cae_a_date_assigned():
    """El fallback histórico a `Date_assigned` era la rama que rompía REG-015.

    Mandaba el update a la app del año equivocado: en 88 jobs de producción el
    año de `Date_assigned` no coincide con el de su app, y 56 de ellos dan 2022,
    que ni siquiera está configurado. Ahora el fallback es `ID_Jobs`, que es el
    contador nativo de Podio y no se puede desincronizar.
    """
    job = Job(ID_Jobs="QID60001", Date_assigned=datetime(2023, 3, 5))
    assert resolve_job_app_year(job) == 2026

    # Y sin ID_Jobs no se inventa nada, aunque haya fecha.
    assert resolve_job_app_year(Job(Date_assigned=datetime(2023, 3, 5))) is None


def test_no_year_resolvable_returns_none():
    # Nunca now(): sin dato, no se sincroniza (queda en PodioFailedSync).
    assert resolve_job_app_year(Job()) is None
