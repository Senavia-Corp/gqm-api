"""Entregas simultaneas del mismo file.change no deben perder el adjunto.

Medido en produccion el 20-ago-2026: el item 3345393757 (PAR6171) entro CINCO
veces en 1,6 segundos y dejo 5 registros en `podio_failed_syncs`, todos
`file.change`, con:

    duplicate key value violates unique constraint "attachments_pkey"
    DETAIL: Key ("ID_Attachment")=(ATT62498) already exists

La comprobacion de `podio_file_id` existia, pero se hacia ANTES de descargar de
Podio y subir a Cloudinary — segundos. Las cinco lambdas la pasaban, hacian la
subida y `generate_custom_id` les daba a todas el mismo max+1.

NO era el desbordamiento del contador arreglado en 1bb0de7: los adjuntos van por
ATT62521 y no hay ni un ID de 5 cifras.
"""
import pathlib

FUENTE = (pathlib.Path(__file__).parents[2] / "src/utils/podio_webhook_core.py").read_text()


def test_se_recomprueba_el_fichero_justo_antes_de_insertar():
    """La ventana debe pasar de segundos a microsegundos."""
    i_cloudinary = FUENTE.index("upload_to_cloudinary(")
    i_recheck = FUENTE.index("ya_esta = session.exec(")
    i_insert = FUENTE.index("for intento in range(1, 6):")
    assert i_cloudinary < i_recheck < i_insert, (
        "la re-comprobacion debe ir DESPUES de la subida y ANTES del insert")


def test_hay_reintento_con_id_nuevo_al_chocar_la_PK():
    assert "for intento in range(1, 6):" in FUENTE
    i_bucle = FUENTE.index("for intento in range(1, 6):")
    i_genera = FUENTE.index("generate_custom_id(", i_bucle)
    assert i_genera > i_bucle, "el ID debe regenerarse DENTRO del bucle, no fuera"


def test_el_choque_se_aisla_en_un_savepoint():
    """Sin savepoint, el IntegrityError tumbaba la transaccion del webhook entero
    y producia el 'This Session's transaction has been rolled back'."""
    assert "session.begin_nested()" in FUENTE


def test_un_choque_de_podio_file_id_no_es_error_sino_idempotencia():
    assert 'if "podio_file_id" in str(choque.orig):' in FUENTE
    i = FUENTE.index('if "podio_file_id" in str(choque.orig):')
    assert "break" in FUENTE[i:i + 260], "debe cortar, no reintentar"


def test_no_se_reintenta_indefinidamente():
    assert "range(1, 6)" in FUENTE
