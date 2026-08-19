"""Huecos declarados: cada registro guarda el `external_id` que ocupa.

No-regresión de G1 y G5 (auditoría 18-ago-2026). Antes la correspondencia
registro ↔ hueco se deducía por posición, así que desaprobar un alquiler corría
a todos los siguientes y vaciar un hueco intermedio reasignaba importes entre
registros distintos.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.EstimateCostModel import EstimateCost
from src.models.JobModel import Job
from src.models.PurchaseModel import Purchase
from src.utils import podio_slots

BDF = "QID.bldg_dept_fees"
MAT = "QID.purchases_list"


@pytest.fixture()
def job_id():
    """Un QID vacío en develop, y su limpieza."""
    jid = f"QIDSLOT{uuid.uuid4().int % 90000 + 10000}"
    with get_session() as s:
        s.add(Job(ID_Jobs=jid, Job_type="QID", podio_app_year=2026))
        s.commit()
    yield jid
    with get_session() as s:
        for m in (EstimateCost, Purchase):
            for r in s.exec(select(m).where(m.ID_Jobs == jid)).all():
                s.delete(r)
        j = s.exec(select(Job).where(Job.ID_Jobs == jid)).first()
        if j:
            s.delete(j)
        s.commit()


def _coste(s, jid, tipo, importe, estado="Approved", slot=None, ident=None):
    ec = EstimateCost(
        ID_EstimateCost=ident or f"ESTT{uuid.uuid4().int % 900000 + 100000}",
        ID_Jobs=jid, Cost_type=tipo, Status=estado,
        Builder_cost=importe, Client_price=importe, podio_field=slot)
    s.add(ec)
    return ec


def test_reservar_respeta_los_huecos_ya_tomados_en_la_base(job_id):
    with get_session() as s:
        fam = podio_slots.familia(BDF)
        a = _coste(s, job_id, "BDF", 100)
        b = _coste(s, job_id, "BDF", 200)
        s.flush()

        assert podio_slots.reservar(s, fam, job_id, a) == "bldg-fees-1"
        assert podio_slots.reservar(s, fam, job_id, b) == "bldg-fees-2"
        s.commit()


def test_reservar_devuelve_none_al_agotarse_y_no_asigna_nada(job_id):
    """Mismo contrato que los change orders: sin hueco no se guarda nada."""
    with get_session() as s:
        fam = podio_slots.familia(BDF)
        for slot in fam.external_ids:
            _coste(s, job_id, "BDF", 10, slot=slot)
        s.flush()

        cuarto = _coste(s, job_id, "BDF", 480)
        s.flush()

        assert podio_slots.reservar(s, fam, job_id, cuarto) is None
        assert cuarto.podio_field is None
        s.rollback()


def test_reservar_no_pisa_un_hueco_que_ya_tiene_valor_en_podio(job_id):
    """En producción hay 7.591 jobs con materiales cargados a mano y sólo 22
    compras en la base: mirar sólo la base haría que la primera compra tomase
    el hueco 1 y borrase lo que el cliente ya tiene."""
    with get_session() as s:
        fam = podio_slots.familia(MAT)
        compra = Purchase(ID_Purchase=f"IHT{uuid.uuid4().int % 90000}",
                          ID_Jobs=job_id, Total_spending=500)
        s.add(compra)
        s.flush()

        en_podio = {"materials-purchased-1-2": [{"value": "999"}],
                    "materials-purchased-2": [{"value": "888"}]}
        assert podio_slots.reservar(s, fam, job_id, compra,
                                    podio_fields=en_podio) == "materials-purchased-3"
        s.rollback()


def test_el_pool_de_13_lo_comparten_alquileres_y_compras(job_id):
    """Es el defecto G1: los alquileres ocupan huecos etiquetados «PURCHASE»."""
    with get_session() as s:
        fam = podio_slots.familia(MAT)
        alquiler = _coste(s, job_id, "Rent", 300)
        compra = Purchase(ID_Purchase=f"IHT{uuid.uuid4().int % 90000}",
                          ID_Jobs=job_id, Total_spending=820)
        s.add(compra)
        s.flush()

        assert podio_slots.reservar(s, fam, job_id, alquiler) == "materials-purchased-1-2"
        # la compra NO puede tomar el hueco del alquiler
        assert podio_slots.reservar(s, fam, job_id, compra) == "materials-purchased-2"
        s.rollback()


def test_liberar_suelta_el_hueco_sin_mover_a_los_demas(job_id):
    """Lo contrario del reparto por posición: soltar el 1 no corre al 2 ni al 3."""
    with get_session() as s:
        fam = podio_slots.familia(BDF)
        a = _coste(s, job_id, "BDF", 100, slot="bldg-fees-1")
        _coste(s, job_id, "BDF", 200, slot="bldg-fees-2")
        c = _coste(s, job_id, "BDF", 300, slot="bldg-dept-fees-3")
        s.flush()

        assert podio_slots.liberar(s, a) == "bldg-fees-1"
        s.flush()

        assert c.podio_field == "bldg-dept-fees-3"
        assert podio_slots.libres_en_bd(s, fam, job_id) == ["bldg-fees-1"]
        # y un alta posterior reutiliza el hueco libre
        d = _coste(s, job_id, "BDF", 400)
        s.flush()
        assert podio_slots.reservar(s, fam, job_id, d) == "bldg-fees-1"
        s.rollback()


def test_payload_por_slot_solo_incluye_lo_declarado(job_id):
    with get_session() as s:
        fam = podio_slots.familia(BDF)
        _coste(s, job_id, "BDF", 120, slot="bldg-fees-1")
        _coste(s, job_id, "BDF", 360, slot="bldg-dept-fees-3")
        s.flush()

        assert podio_slots.payload_por_slot(s, fam, job_id) == {
            "bldg-fees-1": 120.0, "bldg-dept-fees-3": 360.0}
        s.rollback()


def test_el_respaldo_posicional_reproduce_el_comportamiento_de_antes(job_id):
    """Con todo a NULL —el estado justo tras la migración de esquema— el mapper
    tiene que producir exactamente lo de siempre. Es lo que garantiza que
    ningún estado intermedio del despliegue sea peor que hoy."""
    with get_session() as s:
        fam = podio_slots.familia(BDF)
        # IDs explícitos y ordenados: el reparto posicional se ordena por
        # `ID_EstimateCost`, igual que hacía `_build_bdf_array`.
        base = f"ESTT{uuid.uuid4().int % 900000 + 100000}"
        _coste(s, job_id, "BDF", 120, ident=f"{base}A")
        _coste(s, job_id, "BDF", 240, ident=f"{base}B")
        s.flush()

        assert podio_slots.payload_por_slot(s, fam, job_id) == {}
        assert podio_slots.slots_legacy_posicionales(s, fam, job_id) == {
            "bldg-fees-1": 120.0, "bldg-fees-2": 240.0}
        s.rollback()


def test_los_costes_no_aprobados_no_ocupan_hueco(job_id):
    """Regla de negocio V9: un BDF `Estimated` no toca los huecos de Podio."""
    with get_session() as s:
        fam = podio_slots.familia(BDF)
        _coste(s, job_id, "BDF", 100, estado="Estimated")
        s.flush()

        assert podio_slots.libres_en_bd(s, fam, job_id) == list(fam.external_ids)
        s.rollback()
