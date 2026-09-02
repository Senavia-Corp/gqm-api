"""La medida del daño del vaciado: cuenta lo que el arreglo repara, ni más ni menos.

`/admin/podio/obsoletos` existe para cuantificar la deuda del defecto del
1-sep-2026 (vaciar un campo en Podio no lo vaciaba en la BD). Dos exigencias:

1. **Mide lo mismo que arregla el mapeador.** Las columnas salen de
   `campos_vaciables`, la misma función que el mapeador usa para decidir. Si la
   medida tuviera su propia lista, diría algo distinto de lo que pasa en
   producción — el fallo clásico de un oráculo que no comparte código con lo
   que mide.
2. **No presenta una medida parcial como completa** (regla 5 del proyecto).
"""
from src.routes.podio_routes import Paridad
from src.utils.mappers.from_podio.job_mapper import campos_vaciables


class _Job:
    def __init__(self, **kw):
        self.ID_Jobs = kw.pop("ID_Jobs", "QID61001")
        self.Job_type = kw.pop("Job_type", "QID")
        self.podio_item_id = kw.pop("podio_item_id", "100")
        for k, v in kw.items():
            setattr(self, k, v)

    def __getattr__(self, _name):  # cualquier columna no fijada está vacía
        return None


class _ServicioFalso:
    def __init__(self, items):
        self.app_id = "30549028"
        self._items = items

    def get_items_page(self, limit, offset=0):
        lote = self._items[offset:offset + limit]
        return {"items": lote, "filtered": len(self._items),
                "total": len(self._items)}


class _SesionFalsa:
    def __init__(self, filas):
        self._filas = filas

    def exec(self, _stmt):
        return self

    def all(self):
        return self._filas


# ------------------------------------------------- el predicado, en aislado

def test_cuenta_lo_que_la_bd_conserva_y_podio_ya_no_tiene():
    job = _Job(Additional_detail="prueba entrega 2026-09-01")
    hallazgos = Paridad._obsoletos_de_item(
        job, {"Additional_detail": None}, ["Additional_detail"])
    assert hallazgos == {"Additional_detail": "prueba entrega 2026-09-01"}


def test_no_cuenta_si_podio_tiene_valor():
    job = _Job(Additional_detail="algo")
    assert Paridad._obsoletos_de_item(
        job, {"Additional_detail": "algo"}, ["Additional_detail"]) == {}


def test_no_cuenta_si_las_dos_partes_estan_vacias():
    assert Paridad._obsoletos_de_item(
        _Job(), {"Additional_detail": None}, ["Additional_detail"]) == {}


def test_la_cadena_vacia_de_QID61399_no_es_deuda():
    """Tras el intento de limpieza desde el panel la fila quedó con `''`.
    Podio también está vacío: ya convergen, no hay nada que reparar."""
    assert Paridad._obsoletos_de_item(
        _Job(Additional_detail=""), {"Additional_detail": None},
        ["Additional_detail"]) == {}


def test_una_columna_que_el_mapeador_no_declara_no_se_cuenta():
    """Ausente del dict = el mapeador no la considera vaciable en esa app-año.
    Contarla sería inventar deuda donde el arreglo no toca nada."""
    job = _Job(Estimated_completion_date="2026-01-01")
    assert Paridad._obsoletos_de_item(
        job, {}, ["Estimated_completion_date"]) == {}


def test_las_fechas_salen_serializables():
    from datetime import datetime
    job = _Job(Date_assigned=datetime(2026, 8, 1, 12, 30))
    hallazgos = Paridad._obsoletos_de_item(
        job, {"Date_assigned": None}, ["Date_assigned"])
    assert hallazgos == {"Date_assigned": "2026-08-01T12:30:00"}


# ------------------------------------------------- la fuente de las columnas

def test_las_columnas_medidas_son_las_que_el_mapeador_puede_vaciar():
    """Una sola fuente: si divergen, la medida deja de decir nada."""
    vaciables = campos_vaciables("QID", 2026)
    assert "Additional_detail" in vaciables
    # los agregados los reconstruye el recálculo local: no son deuda del sync
    assert "Gqm_formula_pricing" not in vaciables
    # PTL 2026 no tiene estos campos en su app: su ausencia no es un vaciado
    assert "Estimated_completion_date" not in campos_vaciables("PTL", 2026)
    assert "Estimated_completion_date" in campos_vaciables("PTL", 2023)


# ------------------------------------------------- el recorrido y lo parcial

def _montar(monkeypatch, items, filas):
    monkeypatch.setattr(Paridad.podio_jobs_router, "get_readonly_service",
                        lambda t, y: _ServicioFalso(items))
    return _SesionFalsa(filas)


def _item(item_id, tracking, detail=None):
    campos = []
    if detail is not None:
        campos.append({"field_id": 0, "external_id": "superintendent",
                       "type": "text", "values": [{"value": detail}]})
    return {"item_id": item_id, "app_item_id_formatted": tracking,
            "fields": campos}


def test_el_recorrido_encuentra_la_fila_obsoleta(monkeypatch):
    # En Podio el campo está vacío (no viene); en la BD sigue el valor viejo.
    items = [_item(100, "QID61001"), _item(200, "QID61002", "sigue aqui")]
    filas = [_Job(ID_Jobs="QID61001", podio_item_id="100",
                  Additional_detail="valor viejo"),
             _Job(ID_Jobs="QID61002", podio_item_id="200",
                  Additional_detail="sigue aqui")]
    ses = _montar(monkeypatch, items, filas)

    resumen, siguiente = Paridad._medir_obsoletos(ses, "QID", 2026, 200, 0)

    assert siguiente is None and resumen["revisados"] == 2
    assert resumen["jobs_con_valor_obsoleto"] == 1
    assert resumen["por_columna"]["Additional_detail"] == 1
    assert resumen["jobs"][0]["ID_Jobs"] == "QID61001"


def test_un_item_sin_fila_en_la_bd_no_es_este_defecto(monkeypatch):
    """Eso lo mide /parity (faltan/sobran); aquí sólo se cuentan filas vivas."""
    ses = _montar(monkeypatch, [_item(999, "QID61999")], [])
    resumen, _ = Paridad._medir_obsoletos(ses, "QID", 2026, 200, 0)
    assert resumen["revisados"] == 0 and resumen["jobs_con_valor_obsoleto"] == 0


def test_sin_presupuesto_la_medida_se_declara_incompleta(monkeypatch):
    items = [_item(i, f"QID6{i:04d}") for i in range(1, 1200)]
    filas = [_Job(ID_Jobs=f"QID6{i:04d}", podio_item_id=str(i),
                  Additional_detail="viejo") for i in range(1, 1200)]
    ses = _montar(monkeypatch, items, filas)

    resumen, siguiente = Paridad._medir_obsoletos(ses, "QID", 2026, 0, 0)

    assert siguiente is not None, "se agotó el reloj: hay que reencadenar"
    assert resumen["revisados"] < len(items), "no se recorrió la app entera"


def test_el_tope_del_detalle_no_falsea_el_contador(monkeypatch):
    """Un tope silencioso se leería como «esto es todo lo que hay»."""
    monkeypatch.setattr(Paridad, "TOPE_DETALLE", 3)
    items = [_item(i, f"QID6{i:04d}") for i in range(1, 11)]
    filas = [_Job(ID_Jobs=f"QID6{i:04d}", podio_item_id=str(i),
                  Additional_detail="viejo") for i in range(1, 11)]
    ses = _montar(monkeypatch, items, filas)

    resumen, _ = Paridad._medir_obsoletos(ses, "QID", 2026, 200, 0)

    assert resumen["jobs_con_valor_obsoleto"] == 10, "el contador va completo"
    assert resumen["por_columna"]["Additional_detail"] == 10
    assert len(resumen["jobs"]) == 3
    assert resumen["jobs_omitidos_del_detalle"] == 7
