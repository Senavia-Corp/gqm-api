"""El circulo se cierra por el otro lado: lo que Podio entrego y la BD no tiene.

`podio_failed_syncs` solo registra lo que el codigo SABE registrar. La auditoria
del 5-sep-2026 encontro 22 caminos que devuelven 200 sin dead-letter, y midio la
consecuencia: 5 adjuntos entre el 17 y el 20 de agosto (QID61310, QID61285,
QID61225, QID61300, QID61334) con su linea en `tlactivity` y sin fila en
`attachments` — perdidos sin aparecer en ningun contador.

El SQL se valido contra produccion el 6-sep-2026 y devuelve esos 5 exactos.
Estos tests vigilan las tres exclusiones que evitan los falsos positivos, que es
donde un reconciliador se vuelve inutil: si denuncia bajas legitimas, nadie lo
mira.
"""
import re

import src.routes.Webhook_bp as wb

SQL = wb._SQL_ADJUNTOS_PERDIDOS


def test_el_sql_escapa_el_porcentaje_del_like():
    """Con bindparams, psycopg2 interpreta `%`. Un LIKE con `%` simple explota
    con 'unsupported format character' en cuanto la ruta se llama de verdad."""
    like = re.search(r"LIKE\s+'([^']+)'", SQL).group(1)
    assert like == "%%file_ids:%%", (
        "el LIKE tiene que llevar %% o la consulta revienta en produccion")


def test_descarta_los_ficheros_dados_de_baja():
    """Un fichero borrado o reemplazado despues NO es una perdida."""
    assert "bajas AS (" in SQL
    assert "File deleted from Podio" in SQL
    assert "NOT IN (SELECT file_id FROM bajas)" in SQL


def test_descarta_lo_que_ya_tiene_fila_de_fallo():
    """Eso ya se ve en el panel; denunciarlo dos veces es ruido."""
    assert "ya_registrados AS (" in SQL
    assert "NOT IN (SELECT file_id FROM ya_registrados)" in SQL


def test_solo_cuenta_lo_que_NO_esta_en_attachments():
    """La definicion misma de perdida."""
    assert "LEFT JOIN attachments a ON a.podio_file_id = ev.file_id" in SQL
    assert 'a."ID_Attachment" IS NULL' in SQL


def test_exige_que_el_job_exista():
    """Sin job no hay de donde colgar el adjunto: registrarlo seria repetir la
    carrera que cerro el PR #146, no arreglarla."""
    assert 'j."ID_Jobs" IS NOT NULL' in SQL


def test_la_ventana_es_un_parametro_y_no_una_constante():
    """Para poder barrer 7 dias en una revision y 365 en una auditoria."""
    assert ":dias" in SQL


def test_cubre_las_dos_formas_del_payload():
    """Unas filas traen `file_ids` (lista) y otras `file_id` (singular). Mirar
    solo una deja pasar como 'perdido' algo que si tenia fila."""
    assert "COALESCE(f.payload->>'file_ids', f.payload->>'file_id')" in SQL


def test_la_ruta_sigue_protegida_y_separa_medir_de_escribir():
    """GET mide; POST abre expediente. El defecto a evitar es un endpoint que
    escriba en la dead-letter solo por consultarlo."""
    doc = wb.adjuntos_perdidos.__doc__ or ""
    assert "GET" in doc and "POST" in doc
    # @require_permission usa @wraps: si desapareciera, no habria __wrapped__.
    assert hasattr(wb.adjuntos_perdidos, "__wrapped__"), (
        "la ruta tiene que seguir detras de require_permission")
