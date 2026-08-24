"""rescata los adjuntos que se perdieron en la carrera de generate_custom_id

Revision ID: b2r12adjuntos
Revises: a1t11podio
Create Date: 2026-08-23 19:40:00.000000

QUE PASO
--------
Entre el 14 y el 20 de agosto de 2026, varias entregas simultaneas del webhook
`file.change` calcularon el MISMO `ID_Attachment` siguiente y todas menos una
murieron con `duplicate key ... "attachments_pkey"`. Quedaron 12 filas en
`podio_failed_syncs` y 12 ficheros que NUNCA llegaron a la tabla `attachments`.

La causa esta arreglada (`id_counters` + `ux_attachments_podio_file_id`) y
desplegada. El dano no. Medido en produccion el 23-ago-2026:

    SELECT f.id, f.resolved, a."ID_Attachment"
      FROM podio_failed_syncs f
      LEFT JOIN attachments a ON a.podio_file_id = f.payload->>'file_ids';
    -- 12 filas, existe_en_bd = NULL en las 12

Siete de esas filas figuran `resolved = true`. Es MENTIRA: las marco el boton
«Resync», que devolvia "Resync exitoso" sin hacer trabajo porque `file.change`
no casaba con ninguna rama del reintento (ver Webhook_bp.py, guard del 422).

POR QUE NO HACE FALTA BAJAR NADA DE PODIO
-----------------------------------------
La subida a Cloudinary ocurre ANTES del INSERT, asi que los binarios ya estan
subidos —y pagandose— desde agosto. `d6b9f4a37c28` rescato el `link` y el
`cloudinary_public_id` de 11 de las 12 filas al `payload`. Los 11 se
verificaron uno a uno con HTTP: 200 y tamanos reales, de 47 KB a 7,5 MB.

Asi que esto NO re-descarga de Podio ni re-sube a Cloudinary: reconstruye la
fila que falta apuntando al asset que ya existe. Llamar al endpoint phase2 en
su lugar habria subido 11 copias nuevas con `uuid` distinto y dejado los 11
originales huerfanos.

LA 12.a FILA
------------
`id=1` no tiene datos de Cloudinary y no los tuvo nunca: su error fue un corte
SSL durante un SELECT, ANTES de la subida. Ese fichero solo se puede recuperar
volviendo a Podio. Esta migracion la deja en `resolved = false` con la
instruccion en el `error_message`, para que el panel la siga contando como
pendiente en vez de esconderla tras un `true` que era falso.

EL ID SE PIDE AL CONTADOR, NUNCA `max+1`
----------------------------------------
Cada `ID_Attachment` se reserva con el mismo `UPDATE id_counters ... RETURNING`
que usa `generate_custom_id`. Escribir ids a mano por encima de `last_value`
dejaria el contador por detras de la tabla y la siguiente alta de la app
chocaria contra `attachments_pkey` —el fallo se lo traga `audit.py` en
silencio—. Con el contador, queda alineado por construccion.

Escrita a MANO a proposito: el autogenerate de este repo propone siempre
borrar 3 indices CONCURRENTLY que si hacen falta (falso positivo conocido).
"""
from datetime import date
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2r12adjuntos"
down_revision: Union[str, Sequence[str], None] = "a1t11podio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Esta migracion repara UN incidente cerrado y enumerado: las 12 filas que la
# dead-letter acumulo entre el 14 y el 20 de agosto de 2026. El corte la vuelve
# determinista — hace exactamente lo que se reviso, ni una fila mas.
#
# No es cosmetico. El 24-ago entro la fila 13 (QID61359, "Invoice #147833791.pdf"),
# que Cloudinary rechazo por el `#` del nombre: otra causa, y viva. Sin el corte,
# SQL_REABRIR_SIN_DATOS la habria capturado —tambien tiene `link` nulo— y le habria
# antepuesto "sin datos de Cloudinary: el fichero nunca llego a subirse", que en su
# caso es falso. Habria tapado el diagnostico real de un fallo aun sin arreglar.
CORTE_INCIDENTE = "2026-08-21T00:00:00+00:00"


# Filas con datos de recuperacion cuyo fichero sigue SIN estar en la tabla.
# El `NOT EXISTS` es lo que hace la migracion re-ejecutable sin efectos.
SQL_CANDIDATAS = """
SELECT f.id,
       f.payload->>'file_ids'             AS podio_file_id,
       f.payload->>'filename'             AS filename,
       f.payload->>'link'                 AS link,
       f.payload->>'cloudinary_public_id' AS public_id,
       f.payload->>'fk_value'             AS id_jobs
  FROM podio_failed_syncs f
 WHERE f.payload->>'link'     IS NOT NULL
   AND f.payload->>'file_ids' IS NOT NULL
   AND f.payload->>'fk_value' IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM attachments a
                    WHERE a.podio_file_id = f.payload->>'file_ids')
   AND f.created_at < :corte
 ORDER BY f.id
"""

# Reserva atomica, identica a _siguiente_contador de id_generator.py — salvo
# que aqui va en la transaccion de la migracion, no en una conexion aparte:
# retiene el row lock de ('ATT', digito) hasta el commit. Es aceptable porque
# son ~11 INSERT sin red de por medio; un webhook de adjuntos que llegue justo
# en ese instante espera unos milisegundos. Si algun dia esto rescatara miles
# de filas, habria que trocearlo o usar conexion propia como el generador.
SQL_RESERVAR_ID = """
UPDATE id_counters SET last_value = last_value + 1
 WHERE prefix = 'ATT' AND year_digit = :yd
 RETURNING last_value
"""

SQL_INSERTAR = """
INSERT INTO attachments
       ("ID_Attachment", "Document_name", "Link", "Document_type",
        cloudinary_public_id, cloudinary_resource_type, podio_file_id, "ID_Jobs")
VALUES (:att, :nombre, :link, :tipo, :public_id, :rtype, :pfid, :job)
"""

# Solo se cierra lo que se puede DEMOSTRAR: el EXISTS vuelve a mirar la tabla.
SQL_CERRAR = """
UPDATE podio_failed_syncs f
   SET resolved      = true,
       updated_at    = now(),
       error_message = '[rescatada ' || to_char(now(), 'YYYY-MM-DD')
                    || ': fila de attachments reconstruida desde el payload, '
                    || 'fichero verificado en la tabla] '
                    || COALESCE(f.error_message, '')
 WHERE f.id = ANY(:ids)
   AND COALESCE(f.error_message, '') NOT LIKE '[rescatada%'
   AND EXISTS (SELECT 1 FROM attachments a
                WHERE a.podio_file_id = f.payload->>'file_ids')
"""

# Las que no tienen con que reconstruirse dejan de mentir: vuelven a pendiente.
SQL_REABRIR_SIN_DATOS = """
UPDATE podio_failed_syncs f
   SET resolved      = false,
       updated_at    = now(),
       error_message = '[sin datos de Cloudinary: el fichero nunca llego a '
                    || 'subirse. Recuperar con POST '
                    || '/sync_podio/phase2/jobs/attachments/<id_jobs>?year=YYYY] '
                    || COALESCE(f.error_message, '')
 WHERE f.payload->>'link' IS NULL
   AND COALESCE(f.error_message, '') NOT LIKE '[sin datos de Cloudinary%'
   AND NOT EXISTS (SELECT 1 FROM attachments a
                    WHERE a.podio_file_id = f.payload->>'file_ids')
   AND f.created_at < :corte
"""

# Para los `raw` (PDF/Office) Cloudinary no devuelve `format`, asi que el codigo
# guarda el mimetype. Se reproduce lo que habria escrito la app.
_MIME_POR_EXTENSION = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _resource_type(link: str) -> str:
    """`.../<cloud>/image/upload/...` -> "image"; idem "raw" y "video"."""
    prefijo = link.split("/upload/", 1)[0]
    return prefijo.rsplit("/", 1)[-1] if "/upload/" in link else "image"


def _document_type(link: str, filename: str, rtype: str) -> str:
    """Lo mismo que `cloudinary_result["format"].lower() or mimetype`.

    En las imagenes Cloudinary normaliza el formato y lo deja como ULTIMA
    extension de la URL — de ahi el doble sufijo `.jpeg.jpg`, donde el
    `Document_type` real es `jpg`, no `jpeg`.
    """
    if rtype == "image":
        return link.rsplit(".", 1)[-1].lower()
    extension = (filename or "").rsplit(".", 1)[-1].lower()
    return _MIME_POR_EXTENSION.get(extension, "application/octet-stream")


def upgrade() -> None:
    c = op.get_bind()

    # Mismo criterio que generate_custom_id: el digito es el del ano ACTUAL,
    # no el del job. Verificado en produccion: QID51427 es de 2025 y sus
    # adjuntos son ATT62504..ATT62510, con digito 6.
    year_digit = str(date.today().year)[-1]

    candidatas = c.execute(sa.text(SQL_CANDIDATAS),
                           {"corte": CORTE_INCIDENTE}).mappings().all()
    if not candidatas:
        print("[rescate] no hay filas que rescatar; nada que hacer")

    # Falla pronto y con nombre si algun job no existe, en vez de con un error
    # de clave ajena a mitad del bucle.
    jobs = {f["id_jobs"] for f in candidatas}
    if jobs:
        existentes = {
            fila[0] for fila in c.execute(
                sa.text('SELECT "ID_Jobs" FROM jobs WHERE "ID_Jobs" = ANY(:j)'),
                {"j": list(jobs)}).fetchall()}
        ausentes = jobs - existentes
        if ausentes:
            raise RuntimeError(
                f"estos jobs del payload no existen en la tabla jobs: {sorted(ausentes)}")

    insertadas, cerradas_ids = 0, []
    for fila in candidatas:
        rtype = _resource_type(fila["link"])
        tipo = _document_type(fila["link"], fila["filename"], rtype)

        reservado = c.execute(sa.text(SQL_RESERVAR_ID), {"yd": year_digit}).scalar()
        if reservado is None:
            raise RuntimeError(
                f"no existe el contador (prefix='ATT', year_digit='{year_digit}') "
                "en id_counters: sembrarlo antes de ejecutar esta migracion")

        att = f"ATT{year_digit}{reservado:04d}"
        if c.execute(sa.text('SELECT 1 FROM attachments WHERE "ID_Attachment" = :a'),
                     {"a": att}).scalar():
            raise RuntimeError(
                f"el contador entrego {att}, que YA existe en attachments: "
                "id_counters esta por detras de la tabla, revisar antes de seguir")

        c.execute(sa.text(SQL_INSERTAR), {
            "att": att,
            "nombre": fila["filename"],
            "link": fila["link"],
            "tipo": tipo,
            "public_id": fila["public_id"],
            "rtype": rtype,
            "pfid": fila["podio_file_id"],
            "job": fila["id_jobs"],
        })
        insertadas += 1
        cerradas_ids.append(fila["id"])
        print(f"[rescate] {att} <- {fila['id_jobs']} · {fila['filename']} ({tipo}/{rtype})")

    if insertadas != len(candidatas):
        raise RuntimeError(
            f"se insertaron {insertadas} de {len(candidatas)} candidatas")

    cerradas = 0
    if cerradas_ids:
        cerradas = c.execute(sa.text(SQL_CERRAR), {"ids": cerradas_ids}).rowcount
        if cerradas != len(cerradas_ids):
            raise RuntimeError(
                f"se insertaron {insertadas} filas pero solo se pudieron cerrar "
                f"{cerradas}: el EXISTS no encuentra el adjunto recien creado")

    reabiertas = c.execute(sa.text(SQL_REABRIR_SIN_DATOS),
                           {"corte": CORTE_INCIDENTE}).rowcount
    pendientes = c.execute(sa.text(
        "SELECT count(*) FROM podio_failed_syncs WHERE resolved = false")).scalar()

    print(f"[rescate] insertadas={insertadas} cerradas={cerradas} "
          f"reabiertas_sin_datos={reabiertas} pendientes_ahora={pendientes}")


def downgrade() -> None:
    # A proposito no se revierte: deshacerlo volveria a BORRAR los adjuntos
    # recuperados, que es exactamente el dano que esta migracion repara. Si
    # hubiera que retirar alguna fila, se hace una por una y a mano.
    pass
