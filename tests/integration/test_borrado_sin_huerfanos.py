"""Borrar un job no puede dejar filas flotando con `ID_Jobs` NULL.

`purchases`, `opportunities`, `change_orders` y `financial_docs` **no** declaran
cascade en `JobModel.py`, así que SQLAlchemy no falla ni borra: pone la FK a
NULL. La fila queda sin dueño y sin ruido, y solo aparece meses después cuando
alguien cuenta. En producción hoy hay 9 purchases, 8 change_orders y 31
financial_documents así — la huella de los borrados que ya se hicieron.

El test que importa es el del centinela: mide huérfanas antes y después y exige
que no se muevan.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.OpportunitiesModel import Opportunities
from src.models.PurchaseModel import Purchase
from src.utils.borrado_job import (
    TABLAS_HIJAS,
    inventario_dependientes,
    sentinela_huerfanos,
)


@pytest.fixture
def job_con_hijas_sin_cascade():
    """Un job con las dos hijas que el ORM dejaría huérfanas."""
    suf = uuid.uuid4().int % 90000 + 10000
    tracking = f"QID8{suf}"
    with get_session() as s:
        s.add(Job(ID_Jobs=tracking, Job_type="QID", podio_app_year=2026))
        s.add(Purchase(ID_Purchase=f"PURH{suf}", ID_Jobs=tracking, Total_spending=10.0))
        s.add(Opportunities(ID_Opportunities=f"OPPH{suf}", ID_Jobs=tracking))
        s.commit()

    yield tracking

    with get_session() as s:
        for modelo, col in ((Purchase, Purchase.ID_Jobs),
                            (Opportunities, Opportunities.ID_Jobs)):
            for fila in s.exec(select(modelo).where(col == tracking)).all():
                s.delete(fila)
        job = s.exec(select(Job).where(Job.ID_Jobs == tracking)).first()
        if job:
            s.delete(job)
        s.commit()


def test_las_columnas_de_enlace_existen_de_verdad():
    """`chat_message` usa `ID_Job`, singular. Un nombre mal puesto haría que el
    inventario contara 0 dependientes y el borrado pareciera inocuo."""
    from sqlalchemy import text

    with get_session() as s:
        for etiqueta, tabla, columna, _ in TABLAS_HIJAS:
            existe = s.exec(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ).bindparams(t=tabla, c=columna)).scalar()
            assert existe == 1, f"{tabla}.{columna} no existe"


def test_el_inventario_ve_las_hijas_sin_cascade(job_con_hijas_sin_cascade):
    with get_session() as s:
        job = s.exec(select(Job).where(
            Job.ID_Jobs == job_con_hijas_sin_cascade)).first()
        inv = inventario_dependientes(s, job)

    assert inv["dependientes"]["purchase"]["filas"] == 1
    assert inv["dependientes"]["opportunities"]["filas"] == 1
    assert inv["total_dependientes"] == 2
    assert inv["quedarian_huerfanos"] == 2, (
        "las dos son de tablas sin cascade: el borrado las dejaría con ID_Jobs NULL")


def test_borrar_no_deja_huerfanos(job_con_hijas_sin_cascade):
    """La aserción es el punto entero: sin ella el borrado parece limpio."""
    from src.utils.borrado_job import borrar_job_sin_huerfanos

    with get_session() as s:
        antes = sentinela_huerfanos(s)
        job = s.exec(select(Job).where(
            Job.ID_Jobs == job_con_hijas_sin_cascade)).first()

        borrar_job_sin_huerfanos(s, job)
        s.commit()

        assert sentinela_huerfanos(s) == antes
        assert s.exec(select(Job).where(
            Job.ID_Jobs == job_con_hijas_sin_cascade)).first() is None
        assert s.exec(select(Purchase).where(
            Purchase.ID_Jobs == job_con_hijas_sin_cascade)).first() is None


def test_el_borrado_del_orm_a_pelo_SI_deja_huerfanos(job_con_hijas_sin_cascade):
    """Documenta el bug que la función evita, para que nadie la 'simplifique'.

    `session.delete(job)` sin desvincular deja la Purchase con ID_Jobs NULL.
    """
    with get_session() as s:
        antes = sentinela_huerfanos(s)
        job = s.exec(select(Job).where(
            Job.ID_Jobs == job_con_hijas_sin_cascade)).first()

        s.delete(job)
        s.flush()
        despues = sentinela_huerfanos(s)
        s.rollback()   # no dejamos la basura

    assert despues["purchase"] > antes["purchase"], (
        "si esto deja de pasar, el modelo ganó cascade y borrado_job puede simplificarse")


def test_local_jobs_exige_declarar_los_dependientes(
        client, admin_headers, job_con_hijas_sin_cascade):
    tracking = job_con_hijas_sin_cascade

    # Sin el parámetro: 400.
    assert client.delete(
        f"/admin/podio/local_jobs/{tracking}", headers=admin_headers).status_code == 400

    # Con el número equivocado: 409 y no se borra.
    resp = client.delete(
        f"/admin/podio/local_jobs/{tracking}?dependientes_esperados=0",
        headers=admin_headers)
    assert resp.status_code == 409
    assert resp.get_json()["inventario"]["total_dependientes"] == 2

    with get_session() as s:
        assert s.exec(select(Job).where(Job.ID_Jobs == tracking)).first() is not None

    # Con el número correcto: se borra y el centinela no se mueve.
    with get_session() as s:
        antes = sentinela_huerfanos(s)
    resp = client.delete(
        f"/admin/podio/local_jobs/{tracking}?dependientes_esperados=2",
        headers=admin_headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["huerfanos"]["antes"] == antes

    with get_session() as s:
        assert sentinela_huerfanos(s) == antes
        assert s.exec(select(Job).where(Job.ID_Jobs == tracking)).first() is None


def test_no_se_puede_borrar_por_aqui_un_job_que_si_esta_en_podio(client, admin_headers):
    """El endpoint es para locales. Borrar uno sincronizado rompe la paridad."""
    with get_session() as s:
        con_item = s.exec(
            select(Job).where(Job.podio_item_id.is_not(None))).first()
    if not con_item:
        pytest.skip("develop no tiene ningún job con podio_item_id")

    resp = client.delete(
        f"/admin/podio/local_jobs/{con_item.ID_Jobs}?dependientes_esperados=0",
        headers=admin_headers)
    assert resp.status_code == 409
    assert "no es un job local" in resp.get_data(as_text=True)


def test_nietas_cubre_todas_las_fk_del_esquema_real():
    """NIETAS tiene que cubrir TODA hija de las tablas sin cascade.

    Regresión medida en producción el 11-ago-2026: al borrar los jobs locales,
    QID-I60001 y QID-I60003 fallaron con foreign_key_violation porque sus
    `purchase` tenían un `purchase_order` colgando y `desvincular_sin_cascade`
    borraba el padre sin la nieta. Los otros cinco locales pasaron por no tener
    purchases, así que el defecto solo se ve con datos.

    Y no era código viejo: las 13 FK hacia `jobs` las añadieron las migraciones
    de esa misma noche. Por eso este test no compara contra una lista escrita a
    mano — la deriva del esquema es el fallo, así que la lista se deriva del
    esquema. Una migración futura que añada otra hija rompe este test en vez de
    romper un borrado en producción.
    """
    from sqlalchemy import text

    from src.utils.borrado_job import NIETAS, SIN_CASCADE

    padres = [t[1] for t in SIN_CASCADE]
    with get_session() as session:
        reales = session.exec(text("""
            SELECT tgt.relname AS padre, src.relname AS hija
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_class tgt ON tgt.oid = con.confrelid
            WHERE con.contype = 'f' AND tgt.relname = ANY(:padres)
        """).bindparams(padres=padres)).all()

    declaradas = {(p, n[0]) for p, hijas in NIETAS.items() for n in hijas}
    faltan = {(p, h) for p, h in reales} - declaradas

    assert not faltan, (
        f"el esquema tiene hijas de tablas sin cascade que NIETAS no declara: "
        f"{sorted(faltan)}. Borrar un job con esas filas dará "
        f"foreign_key_violation y abortará la transacción entera. "
        f"Añádelas a NIETAS en src/utils/borrado_job.py.")
