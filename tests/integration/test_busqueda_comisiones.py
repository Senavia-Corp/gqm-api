"""El buscador de comisiones devolvía 500 con CUALQUIER término.

`list_commission_table` montaba el OR de búsqueda llamando `.ilike()` sobre
`Year` (INTEGER) y `Total_commission` (DOUBLE PRECISION). Postgres rechaza el
operador al planificar la consulta, no por fila, así que ni siquiera un término
numérico se salvaba:

    operator does not exist: integer ~~* unknown

El panel lo pintaba como "Error 500" y la búsqueda del módulo estaba muerta al
100%. Estos tests fijan las dos mitades del arreglo: que buscar texto funcione y
que buscar números SIGA funcionando (el cast a texto se eligió justo para no
perder buscar por año e importe).

Los datos no se hardcodean: se descubren del propio listado, para que el test no
se rompa cuando develop cambie de contenido.
"""
import pytest

RUTA = "/commission/commission_table"


def _pedir(client, headers, **params):
    from urllib.parse import urlencode

    resp = client.get(f"{RUTA}?{urlencode(params)}", headers=headers)
    assert resp.status_code == 200, (
        f"{RUTA} con {params} devolvió {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]}")
    return resp.get_json()


def _casa(fila, q):
    """Réplica en Python del OR del endpoint: ¿esta fila justifica su presencia?"""
    patron = q.lower()
    campos = [
        fila.get("ID_Commission"),
        fila.get("Month"),
        fila.get("Year"),
        fila.get("Total_commission"),
        (fila.get("member") or {}).get("Member_Name"),
    ]
    return any(patron in str(c).lower() for c in campos if c is not None)


@pytest.fixture(scope="module")
def muestra(app, admin_headers):
    """Una página del listado sin filtrar, de donde salen los términos a buscar."""
    cuerpo = _pedir(app.test_client(), admin_headers, page=1, limit=50)
    if not cuerpo["results"]:
        pytest.skip("develop no tiene comisiones sembradas")
    return cuerpo["results"]


# ----------------------------------------------------------------- el bug vivo
def test_buscar_texto_no_revienta(client, admin_headers, muestra):
    """El fallo original: cualquier término alfabético daba 500."""
    nombre = next(
        (f["member"]["Member_Name"] for f in muestra if f.get("member")), None)
    if not nombre:
        pytest.skip("ninguna comisión de develop tiene miembro asociado")

    q = nombre.split()[0]
    cuerpo = _pedir(client, admin_headers, q=q, page=1, limit=50)

    assert cuerpo["results"], f"buscar '{q}' no devolvió nada y ese miembro existe"
    assert any((f.get("member") or {}).get("Member_Name", "").lower().find(q.lower()) >= 0
               for f in cuerpo["results"]), (
        f"buscar '{q}' no trajo ninguna fila cuyo miembro case: la rama de "
        "Member_Name del OR no está filtrando")
    for f in cuerpo["results"]:
        assert _casa(f, q), f"la fila {f['ID_Commission']} no casa con '{q}'"


# -------------------------------------------- lo que protege la decisión de castear
def test_buscar_por_anio_sigue_funcionando(client, admin_headers, muestra):
    """`Year` es INTEGER: si se hubiera borrado del OR en vez de castearlo,
    buscar el año dejaría de encontrar nada."""
    anio = next((f["Year"] for f in muestra if f.get("Year")), None)
    if anio is None:
        pytest.skip("develop no tiene comisiones con año")

    cuerpo = _pedir(client, admin_headers, q=str(anio), page=1, limit=10)
    assert cuerpo["total"] > 0, f"buscar el año {anio} no devolvió nada"


def test_buscar_por_importe_sigue_funcionando(client, admin_headers, muestra):
    """Lo mismo para `Total_commission` (DOUBLE PRECISION).

    Se elige un importe con decimales: el cast de Postgres lo imprime tal cual
    ('209.75'), mientras que uno entero saldría como '0' y no como '0.0'.
    """
    importe = next(
        (f["Total_commission"] for f in muestra
         if f.get("Total_commission") and float(f["Total_commission"]) % 1), None)
    if importe is None:
        pytest.skip("develop no tiene comisiones con importe decimal")

    cuerpo = _pedir(client, admin_headers, q=str(importe), page=1, limit=10)
    assert cuerpo["total"] > 0, f"buscar el importe {importe} no devolvió nada"


# ------------------------------------------------------------ filas ↔ total
@pytest.mark.parametrize("con_busqueda", [False, True])
def test_las_filas_paginadas_suman_el_total(
        client, admin_headers, muestra, con_busqueda):
    """El `count_stmt` va sobre `stmt.subquery()`: si el WHERE de las filas y el
    del conteo divergen, el panel pagina sobre un total mentiroso."""
    filtros = {}
    if con_busqueda:
        nombre = next(
            (f["member"]["Member_Name"] for f in muestra if f.get("member")), None)
        if not nombre:
            pytest.skip("ninguna comisión de develop tiene miembro asociado")
        filtros["q"] = nombre.split()[0]

    primera = _pedir(client, admin_headers, page=1, limit=20, **filtros)
    total = primera["total"]

    vistas, pagina = len(primera["results"]), 1
    while vistas < total and pagina < 25:
        pagina += 1
        vistas += len(
            _pedir(client, admin_headers, page=pagina, limit=20, **filtros)["results"])

    assert vistas == total, (
        f"{filtros or 'sin filtro'}: total dice {total} pero paginando salen {vistas}")


# ------------------------------------------------ el filtro propio + la búsqueda
def test_read_own_y_busqueda_se_aplican_a_la_vez(
        client, admin_headers, muestra, monkeypatch):
    """`filter_own` y `q` son dos `.where()` encadenados: si la búsqueda pisara
    el filtro propio, un miembro vería comisiones ajenas al buscar.

    Hoy NINGÚN rol tiene concedido `commission:read_own` (solo aparece en esta
    ruta y como comentario en el script de IAM), así que la rama está sin
    ejercitar en producción. Se simula el contexto en vez de tocar el RBAC: el
    JWT de admin sigue pasando `require_permission` —que decodifica el token por
    su cuenta— y dentro del handler estas políticas dan read_all=False.
    """
    duenio = next((f for f in muestra if f.get("member")), None)
    if not duenio:
        pytest.skip("ninguna comisión de develop tiene miembro asociado")
    id_miembro = duenio["member"]["ID_Member"]

    solo_propias = [{
        "Statement": [{
            "Effect": "Allow",
            "Action": ["commission:read_own"],
            "Resource": ["*"],
        }]
    }]
    monkeypatch.setattr(
        "src.routes.Commission.get_user_context",
        lambda: (id_miembro, "member", solo_propias),
    )

    # Se busca un término deliberadamente amplio: el año, que casa con todas.
    anio = duenio.get("Year")
    cuerpo = _pedir(client, admin_headers,
                    q=str(anio) if anio else "a", page=1, limit=50)

    ajenas = [f["ID_Commission"] for f in cuerpo["results"]
              if (f.get("member") or {}).get("ID_Member") != id_miembro]
    assert not ajenas, (
        f"con solo commission:read_own, buscar coló comisiones de otros: {ajenas}")
