"""indice UNICO parcial en attachments.podio_file_id

Revision ID: b4f7c2e18d09
Revises: c3b8d5a1f740
Create Date: 2026-08-21 16:10:00.000000

PRECONDICION del arreglo de la carrera de adjuntos (`97d5a0c`). No es un
"estaria bien": sin este indice ese parche EMPEORA las cosas.

Por que. `97d5a0c` re-comprueba `podio_file_id` justo antes del insert y
reintenta hasta 5 veces regenerando el ID. Con el indice AUSENTE, dos entregas
simultaneas del mismo fichero:

    1. las dos re-comprueban            -> ninguna ha commiteado, las dos pasan
    2. las dos chocan en attachments_pkey  (mismo max+1 de generate_custom_id)
    3. las dos reintentan               -> una saca ATT62499, la otra ATT62500
    4. LAS DOS INSERTAN

Resultado: dos filas y dos assets de Cloudinary de pago para el mismo fichero
de Podio. El parche convierte un fallo ruidoso (IntegrityError) en duplicacion
MUDA. Con el indice puesto, el paso 4 revienta con una violacion sobre
`podio_file_id`, que es justo lo que la rama

    if "podio_file_id" in str(choque.orig): ...

del parche trata como idempotencia. Hoy esa rama es codigo muerto porque la
constraint no existe; esta migracion la hace real.

Parcial (`WHERE podio_file_id IS NOT NULL`) porque los adjuntos subidos desde
la app —no sincronizados desde Podio— no tienen `podio_file_id`. Medido el
21-ago-2026 en produccion: 2.457 filas, 2.446 con `podio_file_id`, o sea 11
sin el. Un unico total las haria colisionar entre ellas.

CONCURRENTLY y `autocommit_block`, como `c3b8d5a1f740` y `373a3e43a266`: la
tabla esta en uso y el equipo del cliente sube ficheros mientras esto corre.

COMO SE APLICA — dos trampas del RUNBOOK-CUTOVER que aplican tal cual aqui:

  1. **Usar la cadena de conexion DIRECTA, no la del pooler.** Los
     `CREATE INDEX CONCURRENTLY` FALLAN a traves de PgBouncer.

  2. **Verificar `indisvalid` DESPUES.** Si el CONCURRENTLY se corta a medias,
     Postgres deja el indice marcado INVALID; y como la sentencia lleva
     `IF NOT EXISTS`, un segundo intento lo da por bueno sin arreglarlo. Un
     indice INVALID no impide duplicados: seria creerse protegido sin estarlo,
     que es peor que no tenerlo.

         SELECT c.relname, i.indisvalid
           FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
          WHERE c.relname = 'ux_attachments_podio_file_id';
         -- indisvalid debe ser TRUE. Si es FALSE:
         --   DROP INDEX CONCURRENTLY ux_attachments_podio_file_id;  y repetir.

Duplicados hoy: CERO (2.446 distintos de 2.446, medido el 21-ago-2026 contra
produccion). La comprobacion de abajo se queda igualmente: si algun dia se
ejecuta con duplicados, para en seco con la lista en vez de dejar un indice
INVALID que Postgres marca y nadie mira.

AVISO — ESTA MIGRACION BIFURCA EL ARBOL. Leer antes de mezclar la PR #94.

`down_revision = c3b8d5a1f740` es correcto: es donde esta PRODUCCION hoy
(`SELECT version_num FROM alembic_version` -> c3b8d5a1f740, medido el
21-ago-2026), y este indice tiene que poder aplicarse YA.

Pero la rama `fix/sync-podio-bidireccional` (PR #94) trae SEIS migraciones
encadenadas y la primera cuelga del MISMO padre:

    c3b8d5a1f740
      |-- b4f7c2e18d09  (esta)
      `-- b1d4a7c05e11 -> b2e5c8d16f22 -> c3f6b9e27a33
                       -> d4a7c1f38b44 -> e5b8d2c94f77 -> f6c9a3e18b55

Al mezclar #94 habra DOS CABEZAS y `alembic upgrade head` se negara a correr
("Multiple head revisions are present").

COMO RESOLVERLO cuando se retome #94: cambiar en `b1d4a7c05e11` su
`down_revision` de `c3b8d5a1f740` a `b4f7c2e18d09`. Una linea, y el arbol
queda lineal. Es preferible a una revision de merge.

TRAMPA AL HACERLO — la base de datos `develop` ya tiene aplicada la cadena
entera de #94 (esta en `f6c9a3e18b55`) SIN este indice. Si se re-apunta la
cadena sin mas, alembic vera `b4f7c2e18d09` como ancestro del version_num
actual y lo dara por aplicado: **el indice no se creara nunca en develop**.
Ahi hay que crearlo a mano con el mismo DDL de `upgrade()`.

AVISO PARA EL PROXIMO AUTOGENERATE — este indice se suma a la lista de falsos
positivos. `alembic revision --autogenerate` propone ahora borrar **CINCO**
indices, no los cuatro de `c3b8d5a1f740`:

    op.drop_index('ix_change_order_job_podio_id', ...)
    op.drop_index('ix_financial_document_id_jobs', ...)
    op.drop_index('ix_order_job_podio_id', ...)
    op.drop_index('ux_jobs_podio_item_id', ...)
    op.drop_index('ux_attachments_podio_file_id', ...)      <- este

Los cinco existen en la BD y ninguno esta declarado en los modelos SQLModel,
asi que autogenerate los ve como deriva. **Quitar esas lineas a mano.**
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b4f7c2e18d09'
down_revision: Union[str, Sequence[str], None] = 'c3b8d5a1f740'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOMBRE = "ux_attachments_podio_file_id"

SQL_DUPLICADOS = """
SELECT podio_file_id, count(*) AS n,
       string_agg("ID_Attachment", ', ' ORDER BY "ID_Attachment")
  FROM attachments
 WHERE podio_file_id IS NOT NULL
 GROUP BY podio_file_id
HAVING count(*) > 1
 ORDER BY n DESC
 LIMIT 20
"""


def upgrade() -> None:
    conexion = op.get_bind()
    duplicados = conexion.exec_driver_sql(SQL_DUPLICADOS).fetchall()
    if duplicados:
        detalle = "; ".join(
            f"file {fid} en {atts} ({n} filas)" for fid, n, atts in duplicados)
        raise RuntimeError(
            f"Hay {len(duplicados)} podio_file_id duplicados; el indice unico no "
            f"puede crearse. Cada duplicado es un fichero de Podio insertado dos "
            f"veces: hay que quedarse con uno y borrar el resto (mirando antes si "
            f"su asset de Cloudinary esta referenciado). Duplicados: {detalle}"
        )

    with op.get_context().autocommit_block():
        op.execute(
            f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {NOMBRE} '
            f'ON attachments (podio_file_id) WHERE podio_file_id IS NOT NULL')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {NOMBRE}")
