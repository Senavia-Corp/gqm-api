"""Cuatro huecos sin camino de vuelta. Uno de ellos ya produjo dano.

(d) `ATTACHMENT_MODEL_MAP` promete `ID_Client` (CLI) e `ID_Community_Tracking`
    (PMC) y esas columnas NO EXISTEN en `attachments`. SQLModel con
    `table=True` no valida: acepta el kwarg, lo deja como atributo suelto e
    INSERTA LA FILA SIN NINGUNA FK.

    No es latente: en produccion hay 3 filas asi —ATT61846, ATT62109,
    ATT62146, todas de carpeta CLI y con podio_file_id— y son los UNICOS 3
    huerfanos de las 2.493.

(c) `elif intento == 5` mandaba a la dead-letter un adjunto que era un
    DUPLICADO IDEMPOTENTE: si el `break` por `podio_file_id` caia en el quinto
    intento, `guardado` seguia False y la condicion se cumplia.

(b) Los adjuntos de entidades que no son Job no tenian recuperador:
    `sync_job_attachments_by_id` lanza ValueError si el ID no empieza por
    QID/PTL/PAR. Exposicion real: 18 con ID_Subcontractor, 3 con ID_BldgDept,
    3 en carpeta CLI.

(a) `podio.others.*` no era reintentable: el parser exige `parts[1] == "jobs"`.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

import src.podio.sync.sync_attachments as sa
import src.utils.podio_webhook_core as core
from src.models.AttachmentsModel import es_fk_de_attachments


# --------------------------------------------------------------------------
# (d) las columnas fantasma
# --------------------------------------------------------------------------
@pytest.mark.parametrize("columna", ["ID_Client", "ID_Community_Tracking"])
def test_las_columnas_que_el_mapa_promete_no_existen(columna):
    """Si algun dia se anaden, este test avisa de que la guarda sobra."""
    assert es_fk_de_attachments(columna) is False, (
        f"{columna} ya existe: revisa si la guarda sigue haciendo falta")


def test_el_mapa_sigue_prometiendolas():
    """Guarda de contexto: si alguien las quita del mapa, esto lo dice."""
    prometidas = {v["fk"] for v in core.ATTACHMENT_MODEL_MAP.values()}
    assert {"ID_Client", "ID_Community_Tracking"} & prometidas, (
        "el mapa dejo de prometer columnas inexistentes: la guarda puede irse")


@pytest.mark.parametrize("funcion", [
    "process_item_attachments", "process_file_change_event"])
def test_no_se_inserta_con_una_fk_inexistente(funcion):
    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(getattr(core, funcion)))))
    assert "es_fk_de_attachments" in codigo, (
        f"{funcion} sigue insertando filas huerfanas en silencio")


def test_la_migracion_de_las_columnas_es_opcional():
    """El codigo NO puede depender de una migracion que no puedo ejecutar."""
    mig = (pathlib.Path(__file__).parents[2] / "migrations" / "versions" /
           "f8b4d2e60a17_attachments_cli_pmc.py")
    assert mig.exists()
    texto = mig.read_text(encoding="utf-8")
    assert "OPCIONAL" in texto
    assert "add_column" in texto


# --------------------------------------------------------------------------
# (c) el duplicado idempotente que iba a la dead-letter
# --------------------------------------------------------------------------
def test_un_duplicado_en_el_quinto_intento_no_es_un_fallo():
    rama = None
    fuente = textwrap.dedent(inspect.getsource(core.process_file_change_event))
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.If) and "== 'file_created'" in ast.unparse(nodo.test):
            rama = "\n".join(ast.unparse(x) for x in nodo.body)
            break
    assert rama, "no existe la rama file_created"

    assert "intento == 5" not in rama, (
        "sigue usando el contador del bucle: un duplicado idempotente en el "
        "quinto intento deja fila de ruido en la dead-letter")
    assert "duplicado" in rama, "falta la bandera propia de item_attachments"


# --------------------------------------------------------------------------
# (b) recuperador para entidades que no son Job
# --------------------------------------------------------------------------
def test_existe_recuperador_para_entidades_que_no_son_job():
    assert hasattr(sa, "sync_entity_attachments_by_id"), (
        "los adjuntos de subcontratistas, bldg depts y clientes siguen sin "
        "ninguna forma de recuperarse")


def test_el_recuperador_rechaza_un_app_type_que_no_sabe_colgar():
    with pytest.raises(ValueError):
        sa.sync_entity_attachments_by_id(
            app_type="LOQUESEA", entity_id="X1", podio_item_id="123")


def test_el_de_jobs_sigue_rechazando_lo_que_no_es_job():
    """Regresion: cada uno en lo suyo."""
    with pytest.raises(ValueError):
        sa.sync_job_attachments_by_id(id_jobs="SUBC60007", year=2026)


# --------------------------------------------------------------------------
# (a) el boton para podio.others
# --------------------------------------------------------------------------
def test_el_resync_sabe_reintentar_podio_others():
    import src.routes.Webhook_bp as wb

    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(wb.resync_failed_sync.__wrapped__))))
    assert "podio.others." in codigo, (
        "`podio.others.*` sigue cayendo en 'hook_type desconocido'")
    assert "sync_entity_attachments_by_id" in codigo


def test_el_resync_de_others_tambien_comprueba_antes_de_cerrar():
    """Mismo criterio que el resto: nada de resolver sin prueba."""
    import src.routes.Webhook_bp as wb

    codigo = ast.unparse(ast.parse(textwrap.dedent(
        inspect.getsource(wb.resync_failed_sync.__wrapped__))))
    i = codigo.find("podio.others.")
    tramo = codigo[i:i + 1600]
    assert "_adjuntos_pendientes" in tramo, (
        "cierra la falla de others sin mirar si el fichero llego")
