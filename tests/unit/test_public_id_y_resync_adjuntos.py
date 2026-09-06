"""
Dos defectos que dejaron un adjunto fuera de la app el 24-ago-2026.

1. `public_id` sin sanear. "Invoice #147833791.pdf" (job QID61359) llego a
   Cloudinary como `Jobs/QID/QID61359/Invoice_#147833791_e0cddbeb.pdf` y
   Cloudinary lo rechazo: `BadRequest: public_id (...) is invalid`. La limpieza
   anterior solo sustituia espacios y barras. Era el primer fichero con un
   caracter prohibido en 2.493 adjuntos.

2. El resync no sabia reintentarlo. `podio.attachment.file_created` caia al
   `else` final con "hook_type desconocido", asi que el boton del panel no
   servia para el unico caso que la dead-letter de adjuntos sabe producir.

Los tests del punto 2 son estaticos (AST): montar Flask + Podio + Cloudinary
para afirmar la forma de una rama cuesta mas de lo que aporta.
"""
import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SERVICE = RAIZ / "src" / "cloudinary" / "service.py"
WEBHOOK = RAIZ / "src" / "routes" / "Webhook_bp.py"


def _cargar_service():
    """Importa service.py con `cloudinary` y `src.config` fingidos.

    El modulo llama a `cloudinary.config(...)` al importarse y `src.config`
    aborta sin SECRET_KEY; nada de eso hace falta para el sanitizador.
    """
    falsos = {}
    cl = types.ModuleType("cloudinary")
    cl.config = lambda **kwargs: None
    up = types.ModuleType("cloudinary.uploader")
    up.upload = up.upload_large = lambda *a, **k: {}
    cl.uploader = up
    cfg = types.ModuleType("src.config")
    cfg.CLOUDINARY_CLOUD_NAME = cfg.CLOUDINARY_API_KEY = cfg.CLOUDINARY_API_SECRET = "x"
    falsos.update({"cloudinary": cl, "cloudinary.uploader": up, "src.config": cfg})

    previos = {k: sys.modules.get(k) for k in falsos}
    sys.modules.update(falsos)
    try:
        spec = importlib.util.spec_from_file_location("_service_bajo_test", SERVICE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in previos.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# --------------------------------------------------------------------------
# 1. El sanitizador
# --------------------------------------------------------------------------
def test_reproduce_el_fallo_real_y_lo_deja_valido():
    """El caso exacto de produccion: QID61359, fila 13 de podio_failed_syncs."""
    f = _cargar_service().sanitizar_para_public_id

    limpio = f("Invoice #147833791")
    public_id = f"Jobs/QID/QID61359/{limpio}_e0cddbeb.pdf"

    assert "#" not in public_id, "la almohadilla que Cloudinary rechazo sigue ahi"
    assert public_id != "Jobs/QID/QID61359/Invoice_#147833791_e0cddbeb.pdf"


@pytest.mark.parametrize("prohibido", list("?&#\\%<>+"))
def test_ningun_caracter_prohibido_sobrevive(prohibido):
    f = _cargar_service().sanitizar_para_public_id
    assert prohibido not in f(f"factura{prohibido}2026")


@pytest.mark.parametrize("nombre", [
    "Unit 314 (2)",                       # parentesis: 8 adjuntos reales
    "Venice Cove - Unit 9-102 (11)",      # guiones y parentesis
    "QID61319-0001 - Invoice",
    "Tapered Insulation Example 2",
    "Park Towers Apartments - Structural Deficiency Report",
])
def test_no_cambia_los_nombres_que_hoy_suben_bien(nombre):
    """Regresion: 2.493 adjuntos subieron con la limpieza vieja.

    El sanitizador nuevo debe darles EL MISMO resultado; si no, los public_id
    dejarian de casar con los que ya estan guardados.
    """
    f = _cargar_service().sanitizar_para_public_id
    viejo = nombre.replace(" ", "_").replace("/", "_")
    assert f(nombre) == viejo


def test_las_barras_siguen_colapsando():
    """Una barra en el nombre partiria el public_id en otra carpeta."""
    f = _cargar_service().sanitizar_para_public_id
    assert "/" not in f("carpeta/fichero")


def test_los_caracteres_de_control_no_pasan():
    f = _cargar_service().sanitizar_para_public_id
    assert f("factura\x00\x1f2026").isprintable()


def test_el_sanitizador_se_aplica_a_nombre_y_extension():
    """Una extension sucia rompe el public_id igual que el nombre."""
    fuente = SERVICE.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)

    subir = next(n for n in ast.walk(arbol)
                 if isinstance(n, ast.FunctionDef) and n.name == "upload_to_cloudinary")
    saneados = {
        n.targets[0].id
        for n in ast.walk(subir)
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "sanitizar_para_public_id"
    }
    assert {"clean_filename", "extension"} <= saneados, (
        f"sin sanear: {{'clean_filename','extension'}} - {saneados}")


# --------------------------------------------------------------------------
# 2. La rama de resync
# --------------------------------------------------------------------------
def _rama_de_adjuntos():
    """Devuelve el nodo `elif` que atiende `podio.attachment.*`."""
    arbol = ast.parse(WEBHOOK.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arbol)
              if isinstance(n, ast.FunctionDef) and n.name == "resync_failed_sync")
    for nodo in ast.walk(fn):
        if not isinstance(nodo, ast.If):
            continue
        prueba = ast.unparse(nodo.test)
        if "podio.attachment." in prueba:
            return nodo
    return None


def test_el_resync_atiende_los_hooks_de_adjunto():
    assert _rama_de_adjuntos() is not None, (
        "`podio.attachment.*` sigue cayendo en 'hook_type desconocido'")


def test_la_rama_invoca_la_recuperacion_existente():
    """Debe reutilizar sync_job_attachments_by_id, no reimplementar la subida."""
    rama = _rama_de_adjuntos()
    llamadas = {ast.unparse(n.func) for n in ast.walk(rama) if isinstance(n, ast.Call)}
    assert "sync_job_attachments_by_id" in llamadas


def test_la_rama_comprueba_que_el_fichero_llego_a_la_tabla():
    """El fallo de agosto fue cerrar sin mirar. Que no se repita.

    Tiene que consultar Attachments DESPUES de reintentar y poder devolver un
    error; si no, volveria a marcar 'resuelto' sin prueba.
    """
    rama = _rama_de_adjuntos()
    cuerpo = ast.unparse(rama)

    assert "Attachments" in cuerpo, "no vuelve a mirar la tabla de adjuntos"
    assert "podio_file_id" in cuerpo, "no busca el fichero por su id de Podio"

    returns = [n for n in ast.walk(rama) if isinstance(n, ast.Return)]
    assert returns, "la rama no puede rechazar nada: cerraria siempre"
    assert any("502" in ast.unparse(r) for r in returns), (
        "falta la salida de error cuando el fichero no aparece en la tabla")


def test_la_rama_no_marca_resuelto_por_su_cuenta():
    """`resolved = True` es del final del endpoint; hacerlo aqui lo adelantaria
    a la comprobacion y reintroduciria el falso positivo."""
    rama = _rama_de_adjuntos()
    for nodo in ast.walk(rama):
        if isinstance(nodo, ast.Assign):
            destino = ast.unparse(nodo.targets[0])
            assert "resolved" not in destino, (
                f"la rama toca `{destino}`; eso lo decide el final del endpoint")


# --------------------------------------------------------------------------
# 3. El tamano y la carpeta (falla 17 de produccion, abierta desde el 28-ago)
# --------------------------------------------------------------------------
def _service_con_espia():
    """Carga el service y sustituye los dos caminos de subida por espias."""
    mod = _cargar_service()
    llamadas = []

    def _resultado(nombre):
        def _fake(*a, **k):
            llamadas.append((nombre, k))
            return {"secure_url": "https://x/y", "public_id": "y",
                    "resource_type": k.get("resource_type", "raw"), "format": "pdf"}
        return _fake

    mod.cloudinary.uploader.upload = _resultado("upload")
    mod.cloudinary.uploader.upload_large = _resultado("upload_large")
    return mod, llamadas


def test_un_pdf_de_19mb_va_troceado_y_no_muere_en_el_tope_de_10mb():
    """La falla 17: 18.887.334 B contra un tope de 10.485.760 B.

    `upload_large` trocea y esquiva el tope, pero solo se usaba para video: un
    PDF grande iba a `upload` y Cloudinary lo rechazaba con 400. Con el codigo
    anterior este test ve "upload" y falla.
    """
    mod, llamadas = _service_con_espia()

    mod.upload_to_cloudinary(
        file_bytes=b"x" * 18_887_334,
        filename="Report ArtSquare Hallandale Beach 082726.pdf",
        mimetype="application/pdf",
        folder="Jobs/QID/QID61298")

    assert [n for n, _ in llamadas] == ["upload_large"], (
        f"se subio por {llamadas[0][0]}: un fichero de 18,9 MB no cabe en la "
        "subida directa de Cloudinary y muere con 400."
    )


def test_un_pdf_pequeno_sigue_yendo_por_la_subida_directa():
    """No cambiar el camino de los ~2.500 ficheros que hoy suben bien."""
    mod, llamadas = _service_con_espia()

    mod.upload_to_cloudinary(
        file_bytes=b"x" * 50_000, filename="ok.pdf",
        mimetype="application/pdf", folder="Jobs/QID/QID61298")

    assert [n for n, _ in llamadas] == ["upload"]


def test_la_carpeta_tambien_se_sanea():
    """`Attachments.py` mete el `access_level` del FORMULARIO en la carpeta.

    Sanear solo el nombre del fichero no sirve de nada si la almohadilla entra
    por la carpeta: el public_id final la lleva igual y Cloudinary responde el
    mismo "public_id (...) is invalid" de la falla 13.
    """
    mod, llamadas = _service_con_espia()

    mod.upload_to_cloudinary(
        file_bytes=b"x", filename="ok.pdf", mimetype="application/pdf",
        folder="Jobs/QID/QID61298/nivel #3")

    carpeta = llamadas[0][1]["folder"]
    assert "#" not in carpeta, f"la almohadilla sobrevivio en la carpeta: {carpeta}"
    assert carpeta.count("/") == 3, (
        f"las barras de la ruta se perdieron: {carpeta}. Sanear la carpeta de "
        "una pieza convierte cada `/` en `_` y aplana el arbol de Cloudinary."
    )
