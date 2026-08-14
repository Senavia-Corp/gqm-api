"""El contrato de `_enumerar`, porque `purge_orphans` borra a partir de él.

`purgar_huerfanas` hacía `encontrados = _enumerar(...)` sin desempaquetar, así
que `encontrados` era la TUPLA. Dos consecuencias encadenadas:

1. `len(encontrados)` valía 2 (el largo de la tupla), no el número de items, así
   que la guarda «la app se movió» saltaba siempre. Fallaba en seguro, y por eso
   nadie lo vio.
2. Si una app llegaba a tener exactamente 2 items, la guarda pasaba — y entonces
   `str(j.podio_item_id) not in encontrados` probaba pertenencia contra la tupla
   `(dict, None)` en vez de contra el dict. Ningún `item_id` está ahí, así que
   **todos** los jobs de ese tipo/año se clasificaban como huérfanos, en un
   endpoint que borra con cascada de 4 niveles.

Lo que se fija aquí es lo que `purge_orphans` necesita: que el primer elemento
sea un dict indexable por `str(item_id)`, y que la aridad no se pueda cambiar sin
romper un test.
"""
from src.routes.podio_routes.Paridad import _enumerar


class _ServicioFalso:
    """Devuelve `items` en una sola página. Sin red."""

    def __init__(self, items):
        self._items = items

    def get_items_page(self, limit, offset=0):
        lote = self._items[offset:offset + limit]
        return {"items": lote, "filtered": len(self._items),
                "total": len(self._items)}


def _item(item_id, formateado, campos=None):
    return {"item_id": item_id, "app_item_id_formatted": formateado,
            "fields": campos or []}


def test_devuelve_tres_elementos():
    """La aridad es parte del contrato: `purge_orphans` desempaqueta."""
    resultado = _enumerar(_ServicioFalso([_item(1, "QID6001")]), 1)
    assert len(resultado) == 3, (
        "si cambia la aridad hay que revisar TODOS los llamadores: uno de ellos "
        "borra filas a partir de esto"
    )


def test_la_pertenencia_por_item_id_funciona():
    """Es la operación exacta que decide si un job es huérfano.

    Contra el código anterior `purge_orphans` hacía este `in` contra la tupla y
    daba False para cualquier id: todos huérfanos.
    """
    items = [_item(101, "QID6001"), _item(102, "QID6002")]
    encontrados, siguiente, _ = _enumerar(_ServicioFalso(items), 2)

    assert siguiente is None
    assert len(encontrados) == 2, "len() tiene que contar items, no elementos de tupla"
    assert "101" in encontrados and "102" in encontrados
    assert "999" not in encontrados
    assert encontrados["101"] == "QID6001"


def test_sin_campos_no_se_baja_nada_extra():
    _, _, crudos = _enumerar(_ServicioFalso([_item(1, "QID6001")]), 1)
    assert crudos == {}, "campos=False no debe cargar la respuesta"


def test_con_campos_se_conservan_los_valores_crudos():
    """Se guarda `values` sin normalizar: es el lado que hace de patrón.

    Y se filtra por tipo, no por una lista de `external_id`, para no heredar el
    mapeo del código que la auditoría tiene que poner a prueba.
    """
    campos = [
        {"external_id": "gqm-target-sold-pricing", "type": "money",
         "label": "GQM (Target) Sold Pricing",
         "values": [{"value": "630.00", "currency": "USD"}]},
        {"external_id": "status", "type": "category", "label": "Status",
         "values": [{"value": {"text": "PAID"}}]},
        {"external_id": "notas-internas", "type": "text", "label": "Notas",
         "values": [{"value": "un parrafo largo que no aporta nada"}]},
    ]
    _, _, crudos = _enumerar(
        _ServicioFalso([_item(7, "QID6007", campos)]), 1, campos=True)

    guardados = crudos["7"]
    assert "notas-internas" not in guardados, "el texto libre no es auditable"
    assert guardados["gqm-target-sold-pricing"]["values"] == [
        {"value": "630.00", "currency": "USD"}], "los valores van sin tocar"
    assert guardados["status"]["values"] == [{"value": {"text": "PAID"}}]
    assert guardados["gqm-target-sold-pricing"]["label"] == "GQM (Target) Sold Pricing"
