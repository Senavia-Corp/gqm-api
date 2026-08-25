"""El borrado en Cloudinary fallaba al 100%, y en silencio.

Medido contra produccion con las 205 filas de identidad persistida como oraculo:
no sobrevive NINGUNA — 180/180 `raw` y 25/25 imagenes.

REG-058 arreglo el endpoint HTTP y dejo sin migrar el camino del WEBHOOK, que es
el normal. Alli convivian dos defectos que se repartian los tipos:

  * los `raw` fallaban por el public_id: se hacia `rsplit(".", 1)` sobre la URL
    y en resource_type=raw el public_id SI lleva la extension.
  * las imagenes fallaban por el resource_type: `get_resource_type` espera un
    MIMETYPE y `Document_type` guarda la EXTENSION para imagenes ('jpg' en 433
    filas, 'png' en 45, 'webp' en 1). Ninguna es clave de RESOURCE_TYPE_MAP, asi
    que caian al default 'raw'.

Y era mudo: se tiraba el booleano de `destroy()`. Por eso se arreglo un camino y
no el otro durante meses.

Los casos de abajo son filas REALES de podio_failed_syncs en produccion.
"""
import ast
import inspect
import textwrap

import pytest

from src.cloudinary.service import get_resource_type, identidad_cloudinary


class _Fila:
    def __init__(self, link, public_id=None, resource_type=None, doc_type=None):
        self.Link = link
        self.cloudinary_public_id = public_id
        self.cloudinary_resource_type = resource_type
        self.Document_type = doc_type


# --------------------------------------------------------------------------
# El helper de identidad
# --------------------------------------------------------------------------
def test_prefiere_la_identidad_persistida():
    """El public_id lleva un sufijo uuid4 (REG-116): NADIE puede reconstruirlo."""
    fila = _Fila(
        link="https://res.cloudinary.com/gqm/raw/upload/v1/Jobs/QID/x.pdf",
        public_id="Jobs/QID/QID61309/Park_e81a5d5d.pdf",
        resource_type="raw")
    assert identidad_cloudinary(fila) == (
        "Jobs/QID/QID61309/Park_e81a5d5d.pdf", "raw")


def test_en_raw_la_extension_se_conserva():
    """Fila real: QID61309. Quitarsela es lo que devolvia "not found"."""
    fila = _Fila(
        "https://res.cloudinary.com/dixmmsqsi/raw/upload/v1786722841/Jobs/QID/"
        "QID61309/Park_Towers_Apartments_-_Structural_Deficiency_Report_e81a5d5d.pdf")
    public_id, resource_type = identidad_cloudinary(fila)

    assert resource_type == "raw"
    assert public_id.endswith(".pdf"), (
        "le quito la extension a un raw: destroy() no encontrara el fichero")


def test_en_imagen_la_extension_se_quita_y_se_decodifica():
    """Fila real: QID61228, 'Unit 314 (2).jpeg'.

    La URL lleva `%28` por el parentesis y una extension `.jpg` que Cloudinary
    anade; el public_id persistido no tiene ni una cosa ni la otra. Derivarlo
    sin `unquote()` daba un public_id que no existe.
    """
    fila = _Fila(
        "https://res.cloudinary.com/dixmmsqsi/image/upload/v1786728094/Jobs/QID/"
        "QID61228/Unit_314_%282%29_ad977cdf.jpeg.jpg")
    public_id, resource_type = identidad_cloudinary(fila)

    assert resource_type == "image", "una imagen se iba a borrar como 'raw'"
    assert public_id == "Jobs/QID/QID61228/Unit_314_(2)_ad977cdf.jpeg", public_id
    assert "%28" not in public_id, "sin unquote(): el public_id no existe asi"


def test_el_resource_type_sale_de_la_url_no_del_document_type():
    """`Document_type` guarda 'jpg' para imagenes, que no es un mimetype."""
    assert get_resource_type("jpg") == "raw", (
        "si esto cambia, el motivo del defecto ya no es el que dice el test")

    fila = _Fila(
        "https://res.cloudinary.com/gqm/image/upload/v1/Jobs/QID/foto.jpg",
        doc_type="jpg")
    assert identidad_cloudinary(fila)[1] == "image"


def test_una_url_sin_upload_no_se_inventa_una_identidad():
    with pytest.raises(ValueError):
        identidad_cloudinary(_Fila("https://ejemplo.com/fichero.pdf"))


# --------------------------------------------------------------------------
# El camino del webhook usa el helper, y ya no es mudo
#
# Via AST a proposito: buscar cadenas en el fuente cuenta tambien los
# COMENTARIOS, y estos hablan de `rsplit` y `get_resource_type` justo para
# explicar por que ya no se usan. Ese fue el vicio del assert textual que este
# PR sustituye en test_delete_verificado_contra_podio.
# --------------------------------------------------------------------------
def _rama(accion, funcion):
    """El `if/elif` de `process_file_change_event` que atiende esa accion.

    `ast.unparse` normaliza las comillas a simples, de ahi el f-string.
    """
    fuente = textwrap.dedent(inspect.getsource(funcion))
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.If) and f"== '{accion}'" in ast.unparse(nodo.test):
            return "\n".join(ast.unparse(x) for x in nodo.body)
    raise AssertionError(f"no existe la rama {accion}")


@pytest.fixture(scope="module")
def file_deleted():
    import src.utils.podio_webhook_core as core
    return _rama("file_deleted", core.process_file_change_event)


def test_el_webhook_usa_la_identidad_persistida(file_deleted):
    """Defecto (a)+(b): nunca leia las columnas, y derivaba mal el resto."""
    assert "identidad_cloudinary" in file_deleted, (
        "el borrado del webhook sigue sin leer la identidad persistida")
    assert "rsplit" not in file_deleted, (
        "sigue derivando el public_id a mano: le quita la extension a los raw")
    assert "get_resource_type" not in file_deleted, (
        "sigue pasandole Document_type (una extension) a get_resource_type")


def test_el_webhook_ya_no_tira_el_booleano_de_destroy(file_deleted):
    """Defecto (c): el fallo era MUDO, por eso duro tanto."""
    llamadas_sueltas = [
        l for l in file_deleted.splitlines()
        if l.strip().startswith("delete_from_cloudinary(")]
    assert not llamadas_sueltas, (
        f"el resultado de destroy() se sigue descartando: {llamadas_sueltas}")
    assert "delete_from_cloudinary" in file_deleted


def test_file_replaced_esta_acotado_a_la_entidad_del_evento():
    """Defecto (e): el SELECT casaba GLOBALMENTE por podio_file_id."""
    import src.utils.podio_webhook_core as core

    rama = _rama("file_replaced", core.process_file_change_event)

    # Hay que mirar EL SELECT, no la rama entera: `_fk_field` aparece tambien en
    # el `record_failed_attachment` del `except`, asi que buscarlo suelto pasaba
    # igual con el filtro global.
    selects = [l for l in rama.splitlines() if "select(Attachments)" in l]
    assert selects, "file_replaced ya no consulta la tabla"
    for linea in selects:
        assert "_fk_field" in linea, (
            "file_replaced sigue buscando el fichero en TODA la tabla: un "
            f"evento de un job da por existente el adjunto de otra entidad\n{linea}")


# --------------------------------------------------------------------------
# El orden del DELETE por HTTP
# --------------------------------------------------------------------------
def test_podio_se_borra_antes_que_cloudinary():
    """Defecto (g).

    Con el orden viejo (Cloudinary -> Podio -> BD), un fallo en Podio abortaba
    con 502 antes de tocar la BD... pero el binario ya no existia: la fila
    sobrevivia con el `Link` muerto y el usuario veia el adjunto hasta que hacia
    clic. Podio primero porque es el unico paso reversible.

    Se mide sobre las LLAMADAS, no sobre los comentarios de seccion.
    """
    import src.routes.Attachments as att

    codigo = ast.unparse(ast.parse(
        textwrap.dedent(inspect.getsource(att.delete_attachment))))

    pos = {
        "podio":      codigo.find("requests.delete"),
        "cloudinary": codigo.find("delete_from_cloudinary"),
        "db":         codigo.find("delete_with_retry"),
    }
    assert -1 not in pos.values(), pos
    assert pos["podio"] < pos["cloudinary"] < pos["db"], pos


def test_la_rama_legacy_dejo_de_parsear_a_mano():
    """Defecto (f): sin unquote() y con get_resource_type(Document_type)."""
    import src.routes.Attachments as att

    codigo = ast.unparse(ast.parse(
        textwrap.dedent(inspect.getsource(att.delete_attachment))))
    assert "identidad_cloudinary" in codigo
    assert "rsplit" not in codigo, "sigue derivando el public_id a mano"


# --------------------------------------------------------------------------
# (d): decision de negocio, no defecto
# --------------------------------------------------------------------------
def test_borrar_un_job_no_borra_el_binario():
    """25-ago-2026: se decide CONSERVAR el binario. Que quede fijado."""
    import inspect

    import src.models.JobModel as jm

    fuente = inspect.getsource(jm)
    i = fuente.find('attachments: List["Attachments"]')
    contexto = fuente[max(0, i - 700):i]
    assert "Cloudinary" in contexto, (
        "sin la nota, el proximo que lea la cascada creera que es un descuido")
