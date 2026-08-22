"""rescata los datos de recuperacion al payload y sanea el volcado SQL viejo

Revision ID: d6b9f4a37c28
Revises: c5a8e3f24b17
Create Date: 2026-08-21 23:40:00.000000

`fe18339` hizo que los fallos NUEVOS se guarden con `sanitize_error()`, que
corta en `[SQL:` y `[parameters:`. Pero las 12 filas ANTERIORES ya tienen el
volcado entero de SQLAlchemy guardado, y el panel las pinta tal cual.

VISTO EN EL PANEL DE PRODUCCION el 21-ago-2026: al pulsar «Sync Errors: 5» en
la pantalla principal de Jobs, el modal muestra en rojo el INSERT completo —
nombre de tabla, las 18 columnas y las URLs de Cloudinary. Es lo primero que ve
quien entra en el modulo.

Hoy esos parametros son metadatos de adjuntos y no hay secreto dentro. Lo malo
es doble: parece un sistema roto cuando no lo esta, y el dia que falle un
INSERT sobre una tabla con columna de token, ese valor queda literal aqui Y
sale por HTTP.

POR QUE ESTA MIGRACION TIENE DOS PASOS, Y NO UNO
------------------------------------------------
La primera version solo recortaba. Estaba MAL, y lo salvo comprobar el dato
antes de escribirlo:

    payload  = {"type","hook_id","item_id","action_type","file_ids"}
    error_message = ... 'Document_name': ..., 'cloudinary_public_id': ...,
                        'Link': 'https://res.cloudinary.com/...'

El `payload` NO tiene nada de Cloudinary. El `error_message` es el UNICO sitio
donde vive el `Link` y el `cloudinary_public_id` de los ficheros que ya se
subieron y nunca se persistieron. Recortar sin mas habria destruido:

  · la unica pista de que assets de Cloudinary estan huerfanos (y facturandose)
  · la posibilidad de recuperar el fichero sin volver a bajarlo de Podio

Asi que primero se RESCATA a `payload` y despues se recorta.

Medido antes de escribir esto: 11 de las 12 filas tienen los datos
extraibles. La 12.a (id=1) no los tiene ni los tuvo nunca — su error fue un
fallo de SSL durante un SELECT, no durante el INSERT, asi que no hubo
parametros que registrar.

REVERSIBLE: no, y es el objetivo. Lo util se conserva en `payload`, que ademas
es JSON consultable en vez de texto que hay que rascar con una regex.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd6b9f4a37c28'
down_revision: Union[str, Sequence[str], None] = 'c5a8e3f24b17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 1 · Rescatar al payload lo que solo existe dentro del volcado.
#     `|| jsonb` fusiona: lo que ya hubiera en payload MANDA sobre lo extraido.
SQL_RESCATAR = """
UPDATE podio_failed_syncs
   SET payload = (
         jsonb_strip_nulls(jsonb_build_object(
           'rescatado_de_error_message', true,
           'filename',             substring(error_message from '''Document_name'': ''([^'']+)'''),
           'cloudinary_public_id', substring(error_message from '''cloudinary_public_id'': ''([^'']+)'''),
           'link',                 substring(error_message from '''Link'': ''([^'']+)'''),
           'fk_value',             substring(error_message from '''ID_Jobs'': ''([^'']+)''')
         )) || COALESCE(payload::jsonb, '{}'::jsonb)
       )::json
 WHERE (error_message LIKE '%[SQL:%' OR error_message LIKE '%[parameters:%')
   AND substring(error_message from '''Link'': ''([^'']+)''') IS NOT NULL
"""

# 2 · Recortar en el marcador que aparezca ANTES, igual que sanitize_error.
SQL_SANEAR = """
UPDATE podio_failed_syncs
   SET error_message = btrim(substring(error_message from 1 for
         LEAST(
           COALESCE(NULLIF(position('[SQL:'        in error_message), 0), 2147483647),
           COALESCE(NULLIF(position('[parameters:' in error_message), 0), 2147483647)
         ) - 1))
 WHERE error_message LIKE '%[SQL:%'
    OR error_message LIKE '%[parameters:%'
"""

SQL_CONTAR = ("SELECT count(*) FROM podio_failed_syncs "
              "WHERE error_message LIKE '%[SQL:%' OR error_message LIKE '%[parameters:%'")


def upgrade() -> None:
    c = op.get_bind()

    antes = c.exec_driver_sql(SQL_CONTAR).scalar()
    c.exec_driver_sql(SQL_RESCATAR)

    rescatadas = c.exec_driver_sql(
        "SELECT count(*) FROM podio_failed_syncs "
        "WHERE payload::jsonb ? 'cloudinary_public_id'").scalar()

    c.exec_driver_sql(SQL_SANEAR)
    despues = c.exec_driver_sql(SQL_CONTAR).scalar()

    print(f"[sanear] con volcado: antes={antes} despues={despues} · "
          f"filas con datos de recuperacion rescatados al payload={rescatadas}")

    if despues:
        raise RuntimeError(
            f"quedan {despues} filas con volcado SQL en error_message")
    if antes and not rescatadas:
        raise RuntimeError(
            "se iba a recortar sin haber rescatado NADA al payload: "
            "revisar las expresiones de extraccion antes de continuar")


def downgrade() -> None:
    # No se puede: el texto recortado no se conserva, y ese es el objetivo.
    # Lo util quedo en `payload`.
    pass
