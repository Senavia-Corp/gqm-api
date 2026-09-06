"""Un `""` en CLI/SUBC/BDEP/PMC no puede borrar el campo en Podio.

`convert_value_for_podio` devuelve `[]` para un `category`/`tag` vacio
(convert_value_podio.py:32-34), y `[]` en Podio **BORRA el campo**, en silencio y
sin error. Los cuatro mappers de /others guardaban el valor con `if value is not
None:`, que es verdadero para `""`, asi que el vacio llegaba hasta ahi.

Es la fuga simetrica de la que `1f6d503` cerro para los jobs el 2-sep-2026. La
regla del cliente es la misma en los dos lados: que la app no conozca un valor no
autoriza a borrarlo en Podio. Vaciar es un acto explicito y va por
`to_podio/limpieza_slots.py`.

Con el codigo anterior estos tests FALLAN: el payload lleva la clave con `[]`.
"""
import pytest

from src.utils.mappers.to_podio.bldg_dept_mapper import map_bldg_dept_to_podio
from src.utils.mappers.to_podio.client_mapper import map_client_to_podio
from src.utils.mappers.to_podio.pa_mgmt_co_mapper import map_parent_to_podio
from src.utils.mappers.to_podio.subcontractor_mapper import map_subc_to_podio


class _Obj:
    """Entidad minima: solo hay que poder hacerle getattr."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, _):        # cualquier atributo no puesto vale None
        return None


@pytest.mark.parametrize("mapper, campo, entidad", [
    (map_client_to_podio, "Client_Status", "cliente"),
    (map_client_to_podio, "Risk_Value", "cliente"),
    (map_subc_to_podio, "Status", "subcontratista"),
    (map_subc_to_podio, "Organization", "subcontratista"),
])
def test_un_vacio_no_viaja_como_lista_vacia(mapper, campo, entidad):
    payload = mapper(_Obj(**{campo: ""}))

    vacios = [k for k, v in payload.items() if v == []]
    assert not vacios, (
        f"el {entidad} manda {vacios} con `[]` por un `\"\"` en {campo}. "
        "Podio interpreta `[]` como BORRAR el campo."
    )


@pytest.mark.parametrize("mapper", [
    map_client_to_podio, map_subc_to_podio,
    map_bldg_dept_to_podio, map_parent_to_podio,
])
def test_ningun_mapper_de_others_emite_lista_vacia_con_todo_a_vacio(mapper):
    """El caso limite: una entidad con TODOS sus campos a `""`.

    No debe salir ni una clave que borre. Con `is not None` sale el payload
    entero lleno de `[]`, o sea un borrado masivo en Podio.
    """
    class _TodoVacio(_Obj):
        def __getattr__(self, _):
            return ""

    payload = mapper(_TodoVacio())
    borradores = {k: v for k, v in payload.items() if v == []}
    assert not borradores, (
        f"{mapper.__name__} emite {len(borradores)} campos con `[]`: "
        f"{sorted(borradores)[:5]}… Eso los borra en Podio."
    )


def test_un_valor_de_verdad_sigue_viajando():
    """La guarda nueva no puede tragarse los valores reales."""
    payload = map_client_to_podio(_Obj(Client_Status="Active"))
    assert any(v for v in payload.values()), (
        "el mapper dejo de mandar un valor real: la guarda se paso de ancha"
    )
