"""Un reintento que falla no puede dejar una fila NUEVA cada vez.

Medido en produccion el 6-sep-2026. Dos pulsaciones de Resync sobre las filas 15
y 17 —una con el fichero borrado en Podio (410 Gone), otra con un PDF que no cabe
en el plan de Cloudinary— dejaron las filas 21, 22, 23 y 24. El panel paso de 5
errores a 6: reintentar EMPEORABA el sintoma y enterraba la fila original entre
copias.

La identidad es (hook_type, item_id, fichero). Las filas 7-11 de agosto eran
cinco ficheros distintos del mismo item y tienen que seguir siendo cinco filas.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.PodioFailedSyncModel import PodioFailedSync
from src.utils.failed_sync import record_failed_attachment


@pytest.fixture()
def marca():
    m = f"ZZD{uuid.uuid4().hex[:10]}"
    yield m
    with get_session() as s:
        for fila in s.exec(select(PodioFailedSync).where(
                PodioFailedSync.item_id == m)).all():
            s.delete(fila)
        s.commit()


def _filas(marca):
    with get_session() as s:
        return s.exec(select(PodioFailedSync).where(
            PodioFailedSync.item_id == marca)).all()


def test_dos_fallos_del_mismo_fichero_dejan_UNA_fila(marca):
    for intento in (1, 2, 3):
        record_failed_attachment(
            item_id=marca, file_id=f"{marca}001", app_type="QID",
            action_type="file_created", fk_field="ID_Jobs", fk_value="QID60001",
            filename="grande.pdf",
            error=RuntimeError(f"File size too large (intento {intento})"))

    filas = _filas(marca)
    assert len(filas) == 1, (
        f"tres reintentos del mismo fichero dejaron {len(filas)} filas. Cada "
        "pulsacion de Resync añadia una copia y el contador subia en vez de bajar."
    )
    assert "intento 3" in filas[0].error_message, (
        "la fila conserva el error del primer intento: no se actualizo, solo se "
        "evito el INSERT"
    )


def test_ficheros_distintos_del_mismo_item_siguen_siendo_filas_distintas(marca):
    """El caso de las filas 7-11: una ráfaga de ficheros del mismo item."""
    for n in (1, 2, 3):
        record_failed_attachment(
            item_id=marca, file_id=f"{marca}00{n}", app_type="QID",
            action_type="file_created", fk_field="ID_Jobs", fk_value="QID60001",
            filename=f"foto{n}.jpg", error=RuntimeError("Cloudinary caido"))

    filas = _filas(marca)
    assert len(filas) == 3, (
        f"tres ficheros distintos quedaron en {len(filas)} filas: la deduplicacion "
        "se paso de ancha y perdio inventario de lo que falta."
    )


def test_una_fila_resuelta_no_absorbe_un_fallo_nuevo(marca):
    """Si el fichero volvio a fallar DESPUES de cerrarse, es un fallo nuevo."""
    record_failed_attachment(
        item_id=marca, file_id=f"{marca}001", app_type="QID",
        action_type="file_created", fk_field="ID_Jobs", fk_value="QID60001",
        filename="x.pdf", error=RuntimeError("primero"))

    with get_session() as s:
        fila = s.exec(select(PodioFailedSync).where(
            PodioFailedSync.item_id == marca)).first()
        fila.resolved = True
        s.add(fila)
        s.commit()

    record_failed_attachment(
        item_id=marca, file_id=f"{marca}001", app_type="QID",
        action_type="file_created", fk_field="ID_Jobs", fk_value="QID60001",
        filename="x.pdf", error=RuntimeError("segundo"))

    filas = _filas(marca)
    assert len(filas) == 2, (
        "un fallo posterior al cierre se metio en la fila ya resuelta: se pierde "
        "que volvio a romperse"
    )
