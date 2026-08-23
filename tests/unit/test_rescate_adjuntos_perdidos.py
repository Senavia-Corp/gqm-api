"""Guardas del rescate de los adjuntos perdidos en agosto de 2026.

Sin BD y sin red a proposito: lo que se comprueba aqui es (a) la derivacion de
campos de la migracion contra los enlaces REALES de produccion y (b) un
invariante estructural que el defecto de `IntegrityError` violaba.

El defecto original: `except IntegrityError` en `process_item_attachments`
(podio_webhook_core.py) con el import hecho DENTRO de otra funcion. Python no
lo ve, lanza `NameError` al evaluar la clausula, y el fichero acababa en la
dead-letter con un error que no era el real — justo en el camino que el 422 del
resync recomienda para recuperar adjuntos.
"""
import ast
import builtins
import importlib.util
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
NUCLEO = RAIZ / "src" / "utils" / "podio_webhook_core.py"
MIGRACION = (RAIZ / "migrations" / "versions"
             / "b2r12adjuntos_rescatar_adjuntos_perdidos.py")


def _cargar_migracion():
    """La migracion importa alembic/sqlalchemy; las funciones probadas son puras."""
    for nombre in ("alembic", "sqlalchemy"):
        sys.modules.setdefault(nombre, types.ModuleType(nombre))
    sys.modules["alembic"].op = None
    spec = importlib.util.spec_from_file_location("_mig_rescate", MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _ligados_en(cuerpo) -> set:
    """Nombres ligados en un ambito, SIN descender a los anidados.

    Recursion explicita y no `ast.walk`, que aplana el arbol entero y no se
    puede podar: con walk, un import hecho dentro de una funcion contaria como
    visible desde el modulo — que es justo el error que este guarda persigue.
    """
    ligados = set()

    def recorrer(nodo):
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            ligados.update(a.asname or a.name.split(".")[0] for a in nodo.names)
            return
        if isinstance(nodo, _DEFS + (ast.ClassDef,)):
            ligados.add(nodo.name)
            return  # su cuerpo es otro ambito
        if isinstance(nodo, ast.Name) and isinstance(nodo.ctx, ast.Store):
            ligados.add(nodo.id)
        for hijo in ast.iter_child_nodes(nodo):
            recorrer(hijo)

    for nodo in cuerpo:
        recorrer(nodo)
    return ligados


def _except_sin_ligar(nodo, visibles: set) -> list:
    """Recorre respetando el ambito: modulo -> funcion -> funcion anidada."""
    huerfanos = []
    if isinstance(nodo, _DEFS):
        visibles = visibles | _ligados_en(nodo.body) | {
            a.arg for a in nodo.args.args + nodo.args.kwonlyargs}

    if isinstance(nodo, ast.ExceptHandler) and nodo.type is not None:
        capturadas = (nodo.type.elts if isinstance(nodo.type, ast.Tuple)
                      else [nodo.type])
        huerfanos += [f"{c.id} (linea {c.lineno})" for c in capturadas
                      if isinstance(c, ast.Name) and c.id not in visibles]

    for hijo in ast.iter_child_nodes(nodo):
        huerfanos += _except_sin_ligar(hijo, visibles)
    return huerfanos


_B = "https://res.cloudinary.com/dixmmsqsi"

# Los 11 ficheros que la migracion reconstruye, con sus enlaces tal cual estan
# hoy en `podio_failed_syncs.payload` en produccion. Los valores esperados son
# los que ya tienen los adjuntos vecinos de esos mismos jobs.
ENLACES_REALES = [
    (f"{_B}/raw/upload/v1786722841/Jobs/QID/QID61309/"
     "Park_Towers_Apartments_-_Structural_Deficiency_Report_e81a5d5d.pdf",
     "Park Towers Apartments - Structural Deficiency Report.pdf",
     "raw", "application/pdf"),
    (f"{_B}/image/upload/v1786728094/Jobs/QID/QID61228/Unit_314_%282%29_ad977cdf.jpeg.jpg",
     "Unit 314 (2).jpeg", "image", "jpg"),
    (f"{_B}/image/upload/v1786728096/Jobs/QID/QID61228/Unit_314_%281%29_72ba2c0a.jpeg.jpg",
     "Unit 314 (1).jpeg", "image", "jpg"),
    (f"{_B}/image/upload/v1786728103/Jobs/QID/QID61228/Unit_314_Kitchen_%282%29_83ce9aae.jpeg.jpg",
     "Unit 314 Kitchen (2).jpeg", "image", "jpg"),
    (f"{_B}/raw/upload/v1787152041/Jobs/QID/QID61319/QID61319-0001_-_Invoice_9e3fc0ec.pdf",
     "QID61319-0001 - Invoice.pdf", "raw", "application/pdf"),
    (f"{_B}/image/upload/v1787237453/Jobs/PAR/PAR6171/Venice_Cove_-_Unit_9-102_%281%29_90a951c3.jpeg.jpg",
     "Venice Cove - Unit 9-102 (1).jpeg", "image", "jpg"),
    (f"{_B}/image/upload/v1787237453/Jobs/PAR/PAR6171/Venice_Cove_-_Unit_9-102_%288%29_fc4eb98d.jpeg.jpg",
     "Venice Cove - Unit 9-102 (8).jpeg", "image", "jpg"),
    (f"{_B}/image/upload/v1787237453/Jobs/PAR/PAR6171/Venice_Cove_-_Unit_9-102_%2811%29_9481fa42.jpeg.jpg",
     "Venice Cove - Unit 9-102 (11).jpeg", "image", "jpg"),
    (f"{_B}/image/upload/v1787237453/Jobs/PAR/PAR6171/Venice_Cove_-_Unit_9-102_%286%29_b39cd472.jpeg.jpg",
     "Venice Cove - Unit 9-102 (6).jpeg", "image", "jpg"),
    (f"{_B}/image/upload/v1787237455/Jobs/PAR/PAR6171/Venice_Cove_-_Unit_9-102_%284%29_1c8d3d54.jpeg.jpg",
     "Venice Cove - Unit 9-102 (4).jpeg", "image", "jpg"),
    (f"{_B}/image/upload/v1787242902/Jobs/QID/QID51427/Tapered_Insulation_Example_2_0fefdfd4.jpg.jpg",
     "Tapered Insulation Example 2.jpg", "image", "jpg"),
]


@pytest.mark.parametrize("link,nombre,rtype_esp,tipo_esp", ENLACES_REALES)
def test_derivacion_contra_los_enlaces_reales(link, nombre, rtype_esp, tipo_esp):
    """El `Document_type` de una imagen es el formato al que Cloudinary convirtio.

    De ahi el doble sufijo `.jpeg.jpg`: el valor bueno es `jpg`, no `jpeg`.
    Para los `raw` Cloudinary no devuelve `format` y el codigo guarda el
    mimetype, asi que un PDF queda como `application/pdf`.
    """
    mig = _cargar_migracion()
    rtype = mig._resource_type(link)
    assert rtype == rtype_esp
    assert mig._document_type(link, nombre, rtype) == tipo_esp


def test_derivacion_no_revienta_con_entradas_raras():
    mig = _cargar_migracion()
    assert mig._resource_type("https://ejemplo/sin-marcador.jpg") == "image"
    assert mig._document_type("x", "cosa.rara", "raw") == "application/octet-stream"
    assert mig._document_type("x", None, "raw") == "application/octet-stream"


def test_el_id_reservado_usa_el_formato_de_id_generator():
    """`ANCHO = 4` en id_generator.py: ATT + digito de anio + 4 cifras."""
    assert f"ATT{'6'}{2537:04d}" == "ATT62537"


def test_todo_except_resuelve_en_el_ambito_de_modulo():
    """Una excepcion capturada por nombre tiene que estar ligada en el MODULO.

    Este es el invariante que rompia el defecto: el import vivia dentro de otra
    funcion, asi que el `except` de `process_item_attachments` no veia el
    nombre y lanzaba `NameError` en vez de capturar nada.
    """
    arbol = ast.parse(NUCLEO.read_text(encoding="utf-8"))
    visibles = _ligados_en(arbol.body) | set(dir(builtins))
    huerfanos = _except_sin_ligar(arbol, visibles)

    assert not huerfanos, (
        "estas excepciones se capturan por un nombre que no esta ligado a nivel "
        f"de modulo y lanzaran NameError: {huerfanos}")


def test_process_item_attachments_pide_el_id_dentro_de_un_bucle():
    """El ID se pedia UNA vez: si chocaba, el fichero se perdia al primer intento.

    Es la colision de `attachments_pkey` que dejo 12 adjuntos sin insertar.
    """
    arbol = ast.parse(NUCLEO.read_text(encoding="utf-8"))
    funcion = next(
        (n for n in ast.walk(arbol)
         if isinstance(n, ast.FunctionDef) and n.name == "process_item_attachments"),
        None)
    assert funcion is not None, "no existe process_item_attachments"

    llamadas = [n for n in ast.walk(funcion)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "generate_custom_id"]
    assert llamadas, "process_item_attachments ya no pide ID_Attachment"

    # `resincronizar` es el marcador semantico del reintento, no el `for`: la
    # funcion ya tenia un `for file in files` que englobaba la llamada aun con
    # el defecto. Sin ese argumento se reintentaria contra el mismo numero.
    sin_resincronizar = [n.lineno for n in llamadas
                         if not any(k.arg == "resincronizar" for k in n.keywords)]
    assert not sin_resincronizar, (
        "generate_custom_id se llama sin `resincronizar` en las lineas "
        f"{sin_resincronizar}: una colision de ID mandaria el adjunto a la "
        "dead-letter al primer intento, que es lo que perdio los 12 adjuntos")

    # Y ademas debe estar dentro de un bucle acotado `for ... in range(...)`.
    en_range = {
        id(c)
        for bucle in ast.walk(funcion)
        if isinstance(bucle, ast.For) and isinstance(bucle.iter, ast.Call)
        and isinstance(bucle.iter.func, ast.Name) and bucle.iter.func.id == "range"
        for c in ast.walk(bucle)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        and c.func.id == "generate_custom_id"
    }
    assert {id(n) for n in llamadas} == en_range, (
        "la peticion de ID_Attachment no esta dentro de un bucle de reintento acotado")
