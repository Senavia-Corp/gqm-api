"""anade ID_Client e ID_Community_Tracking a attachments

Revision ID: f8b4d2e60a17
Revises: e7a3c9d21f80
Create Date: 2026-08-25

OPCIONAL. El codigo NO depende de esta migracion.

`ATTACHMENT_MODEL_MAP` promete `ID_Client` (CLI) e `ID_Community_Tracking` (PMC)
y esas columnas no existen en `attachments`. SQLModel con `table=True` no valida
nada: acepta el kwarg, lo deja como atributo suelto e INSERTA LA FILA SIN
NINGUNA FK.

Dano ya hecho, medido el 25-ago-2026 en produccion:

    ATT61846, ATT62109, ATT62146
    carpeta CLI, con podio_file_id, TODAS las FK a NULL
    huerfanos en toda la tabla: 3 — son exactamente esos

El PR que trae esta migracion cierra la corrupcion SIN ella: `es_fk_de_attachments`
comprueba que la columna existe antes de insertar y, si no, manda el fichero a la
dead-letter en vez de dejar una fila huerfana. Eso ya no depende de que nadie
corra nada.

Esta migracion es la OTRA salida: si el negocio quiere que CLI y PMC tengan
adjuntos de verdad, aqui estan sus columnas. Aplicarla hace que la guarda deje
de rechazarlos automaticamente, sin tocar codigo.

Si se decide que CLI y PMC NO deben tener adjuntos, no la apliques: borra sus
dos entradas de ATTACHMENT_MODEL_MAP y esta migracion sobra.

LAS 3 FILAS HUERFANAS NO SE TOCAN AQUI. Aplicar esto no las repara: sus FK
siguen a NULL y no hay dato para reconstruirlas mas alla de la carpeta `CLI/`
del `Link`. Repararlas o borrarlas es una decision aparte.

AVISO: el autogenerate propondra borrar los indices unicos parciales que no
estan declarados en los modelos. Quitar esas lineas a mano.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8b4d2e60a17"
down_revision: Union[str, Sequence[str], None] = "e7a3c9d21f80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNAS = (
    ("ID_Client", "client", "ID_Client"),
    ("ID_Community_Tracking", "parent_mgmt_co", "ID_Community_Tracking"),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existentes = {c["name"] for c in inspector.get_columns("attachments")}
    tablas = set(inspector.get_table_names())

    for columna, tabla_ref, col_ref in COLUMNAS:
        if columna in existentes:
            continue
        op.add_column("attachments",
                      sa.Column(columna, sa.String(), nullable=True))
        # La FK solo si la tabla referenciada existe con ese nombre; en algunos
        # entornos el nombre difiere y no merece la pena abortar por eso.
        if tabla_ref in tablas:
            op.create_foreign_key(
                f"fk_attachments_{columna.lower()}", "attachments", tabla_ref,
                [columna], [col_ref])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existentes = {c["name"] for c in inspector.get_columns("attachments")}
    for columna, _, _ in COLUMNAS:
        if columna not in existentes:
            continue
        try:
            op.drop_constraint(f"fk_attachments_{columna.lower()}",
                               "attachments", type_="foreignkey")
        except Exception:
            pass
        op.drop_column("attachments", columna)
