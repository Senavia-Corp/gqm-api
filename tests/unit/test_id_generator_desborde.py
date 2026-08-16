"""El contador de generate_custom_id al pasar de 9999.

En produccion (16-ago-2026) `tlactivity` llevaba 88 dias sin escribir: 9 736
filas TLA6xxxx y UNA sola TLA610000, la ultima registrada. La causa era el
`ORDER BY id DESC` lexicografico — "TLA69999" > "TLA610000" como texto — que
dejaba el generador clavado devolviendo un ID ya existente. El IntegrityError
lo absorbia el `except` de log_activity, asi que fallaba en silencio.
"""
from typing import Optional

import pytest
from sqlmodel import Field, SQLModel, Session, create_engine

from src.utils.id_generator import generate_custom_id


class _Fila(SQLModel, table=True):
    __tablename__ = "fila_prueba_id_generator"
    ID_Cosa: Optional[str] = Field(default=None, primary_key=True)


@pytest.fixture
def sesion():
    motor = create_engine("sqlite://")
    SQLModel.metadata.create_all(motor, tables=[_Fila.__table__])
    with Session(motor) as s:
        yield s


def _sembrar(sesion, ids):
    for valor in ids:
        sesion.add(_Fila(ID_Cosa=valor))
    sesion.commit()


def test_tabla_vacia_arranca_en_0001(sesion):
    assert generate_custom_id(sesion, _Fila, "ID_Cosa", "TLA").endswith("0001")


def test_cuenta_normal_por_debajo_de_9999(sesion):
    _sembrar(sesion, ["TLA60001", "TLA60002", "TLA60003"])
    assert generate_custom_id(sesion, _Fila, "ID_Cosa", "TLA")[-4:] == "0004"


def test_al_pasar_de_9999_el_ancho_crece_y_no_se_repite(sesion):
    _sembrar(sesion, ["TLA69998", "TLA69999"])
    nuevo = generate_custom_id(sesion, _Fila, "ID_Cosa", "TLA")
    assert nuevo.endswith("10000"), nuevo


def test_no_se_queda_clavado_una_vez_existe_el_de_5_cifras(sesion):
    """El caso exacto que rompio produccion: con 9999 Y 10000 en la tabla, el
    orden lexicografico devolvia 9999 y se reintentaba 10000 para siempre."""
    _sembrar(sesion, ["TLA69999", "TLA610000"])
    nuevo = generate_custom_id(sesion, _Fila, "ID_Cosa", "TLA")
    assert nuevo.endswith("10001"), nuevo


def test_sigue_avanzando_bien_entrado_el_desborde(sesion):
    _sembrar(sesion, ["TLA69999", "TLA610000", "TLA610001", "TLA610002"])
    assert generate_custom_id(sesion, _Fila, "ID_Cosa", "TLA").endswith("10003")


def test_los_ids_legacy_sin_sufijo_numerico_no_reinician_el_contador(sesion):
    """Antes un ID no numerico hacia `next_num = 1` y colisionaba con los ya
    usados; ahora se ignora y el maximo real manda."""
    _sembrar(sesion, ["TLA60007", "TLAX", "TLA6"])
    assert generate_custom_id(sesion, _Fila, "ID_Cosa", "TLA").endswith("0008")


def test_otros_prefijos_no_se_mezclan(sesion):
    _sembrar(sesion, ["TLA60050", "ORD60900"])
    assert generate_custom_id(sesion, _Fila, "ID_Cosa", "ORD").endswith("0901")
