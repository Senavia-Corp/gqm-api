"""indice UNICO parcial e insensible a mayusculas en los correos de acceso

Revision ID: e9c1correo
Revises: f8b4d2e60a17
Create Date: 2026-09-06 00:00:00.000000

O-02 de la auditoria de portal. Medido: se crearon DOS tecnicos con el mismo
correo, ambos con 201, y el login resuelve SIEMPRE a la primera fila. La segunda
cuenta existe, ocupa el correo y nadie puede entrar en ella jamas. No habia
ningun indice unico sobre `Email_Address` en `member`, `subcontractor` ni
`technician` — verificado contra pg_indexes.

Importa AHORA y no despues porque el alta del portal son 432 subcontratistas
importados de Podio. Entre 432 registros, un correo repetido no da error: crea
una cuenta muda en silencio. Sin indice, ese fallo no tiene como manifestarse.

POR QUE lower(): el login normaliza el correo a minusculas para los tres tipos
de principal (ver Login_auth.py, hallazgo O-04). Un indice sensible a
mayusculas dejaria pasar 'Ana@x.com' y 'ana@x.com' como filas distintas que la
busqueda del login colapsa en una sola — exactamente el mismo agujero, escrito
de otra forma.

Parcial (`WHERE Email_Address IS NOT NULL`) porque hay filas historicas sin
correo y un unico total las haria colisionar entre ellas. Esas filas no pueden
iniciar sesion, asi que no son un problema de acceso.

CONCURRENTLY y `autocommit_block`, como c3b8d5a1f740 y 373a3e43a266: son tablas
de produccion y no se pueden bloquear para escritura durante el cutover.

ORDEN DE EJECUCION — importa. Esta migracion va DESPUES de sanear duplicados con
`scripts/sanear_correos_duplicados.py`. Si se ejecuta antes y hay duplicados, la
comprobacion de abajo la para en seco CON LA LISTA, en vez de dejar un indice
invalido que Postgres marca y nadie mira.

AVISO PARA EL PROXIMO AUTOGENERATE: estos tres indices no estan declarados en los
modelos SQLModel, asi que `alembic revision --autogenerate` los vera como deriva
y propondra borrarlos. Quitar esas lineas a mano, como ya pasa con los cuatro que
documenta c3b8d5a1f740.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e9c1correo'
down_revision: Union[str, Sequence[str], None] = 'f8b4d2e60a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (tabla, columna de id, nombre del indice)
TABLAS = [
    ("member", "ID_Member", "ux_member_email_lower"),
    ("subcontractor", "ID_Subcontractor", "ux_subcontractor_email_lower"),
    ("technician", "ID_Technician", "ux_technician_email_lower"),
]

SQL_DUPLICADOS = """
SELECT lower("Email_Address") AS correo,
       count(*) AS n,
       string_agg("{id_col}", ', ' ORDER BY "{id_col}") AS filas
  FROM {tabla}
 WHERE "Email_Address" IS NOT NULL AND btrim("Email_Address") <> ''
 GROUP BY lower("Email_Address")
HAVING count(*) > 1
 ORDER BY n DESC
 LIMIT 20
"""


def upgrade() -> None:
    conexion = op.get_bind()

    # Primero se comprueban las TRES tablas y se acumula: si hay duplicados en
    # dos de ellas, el operador debe verlos de una vez y no descubrir la segunda
    # tanda tras arreglar la primera y volver a desplegar.
    problemas = []
    for tabla, id_col, _ in TABLAS:
        filas = conexion.exec_driver_sql(
            SQL_DUPLICADOS.format(tabla=tabla, id_col=id_col)).fetchall()
        for correo, n, ids in filas:
            problemas.append(f"{tabla}: «{correo}» en {n} filas ({ids})")

    if problemas:
        raise RuntimeError(
            "Hay correos duplicados; el indice unico no puede crearse todavia.\n"
            "Saneelos primero con:\n"
            "    .venv/bin/python scripts/sanear_correos_duplicados.py            # informe\n"
            "    .venv/bin/python scripts/sanear_correos_duplicados.py --aplicar\n\n"
            + "\n".join(problemas)
        )

    with op.get_context().autocommit_block():
        for tabla, _, nombre in TABLAS:
            op.execute(
                f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {nombre} '
                f'ON {tabla} (lower("Email_Address")) '
                f'WHERE "Email_Address" IS NOT NULL'
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for _, _, nombre in TABLAS:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
