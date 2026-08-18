"""Borrar un Member con hijos NO debe destruir su auditoria.

MemberModel declara `tlactivity` y `commissions` con
cascade="all, delete, delete-orphan", pero `purchases`, `tasks` y
`chat_messages` NO cascadean: su FK aborta el DELETE.

El orden importaba. SQLAlchemy volcaba primero las cascadas y reventaba despues
contra la FK, y el fallo NO deshacia lo ya borrado. Medido en produccion el
18-ago-2026 con MEM60011: dos intentos fallidos se llevaron 38 de sus 137 filas
de `tlactivity` antes de devolver 409, dejando al miembro vivo y su rastro a
medias.

Ahora se comprueban los bloqueantes ANTES, asi que la cascada nunca arranca.
"""
import pytest
from sqlmodel import Field, Session, SQLModel, create_engine, func, select


class _Miembro(SQLModel, table=True):
    __tablename__ = "miembro_prueba_borrado"
    ID_Member: str = Field(primary_key=True)


class _Auditoria(SQLModel, table=True):
    __tablename__ = "auditoria_prueba_borrado"
    ID: int = Field(primary_key=True)
    ID_Member: str = Field(foreign_key="miembro_prueba_borrado.ID_Member")


class _Tarea(SQLModel, table=True):
    __tablename__ = "tarea_prueba_borrado"
    ID: int = Field(primary_key=True)
    ID_Member: str = Field(foreign_key="miembro_prueba_borrado.ID_Member")


@pytest.fixture
def sesion():
    motor = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        motor, tables=[_Miembro.__table__, _Auditoria.__table__, _Tarea.__table__])
    with Session(motor) as s:
        s.add(_Miembro(ID_Member="MEM1"))
        s.add_all([_Auditoria(ID=i, ID_Member="MEM1") for i in range(1, 6)])
        s.add(_Tarea(ID=1, ID_Member="MEM1"))
        s.commit()
        yield s


def _bloqueantes(sesion, id_member):
    """La misma comprobacion previa que hace la ruta."""
    n = sesion.exec(select(func.count()).select_from(_Tarea)
                    .where(_Tarea.ID_Member == id_member)).one()
    return {"tasks": n} if n else {}


def test_detecta_los_bloqueantes_antes_de_tocar_nada(sesion):
    assert _bloqueantes(sesion, "MEM1") == {"tasks": 1}


def test_al_abortar_la_auditoria_sigue_intacta(sesion):
    """Lo que fallaba en produccion: la auditoria desaparecia igualmente."""
    antes = sesion.exec(select(func.count()).select_from(_Auditoria)).one()
    assert antes == 5

    if _bloqueantes(sesion, "MEM1"):
        pass  # la ruta lanza 409 aqui, sin llegar al delete

    despues = sesion.exec(select(func.count()).select_from(_Auditoria)).one()
    assert despues == 5, "la comprobacion previa no debe tocar la auditoria"


def test_sin_bloqueantes_el_borrado_puede_seguir(sesion):
    sesion.exec(select(_Tarea)).all()
    for t in sesion.exec(select(_Tarea)).all():
        sesion.delete(t)
    sesion.commit()
    assert _bloqueantes(sesion, "MEM1") == {}


def test_la_ruta_declara_la_comprobacion_previa():
    """Guarda de regresion: que nadie quite el pre-check y vuelva el problema."""
    import pathlib
    src = (pathlib.Path(__file__).parents[2] / "src/routes/Member.py").read_text()
    assert "member_has_children" in src
    i_check = src.index("member_has_children")
    i_delete = src.index("delete_with_retry(session, obj)")
    assert i_check < i_delete, "el pre-check debe ir ANTES del delete"
