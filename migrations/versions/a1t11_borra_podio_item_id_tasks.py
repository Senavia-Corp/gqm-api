"""T-11: borra tasks.podio_item_id — campo muerto.

Las tareas nunca sincronizaron con Podio: ningún fichero de src/podio/ las
menciona, config.py nunca leyó TAS_TAP_APP_ID/TOKEN, y las 153 filas de
producción tienen podio_item_id = NULL. Se retira el campo y su índice.

Escrita a MANO a propósito: el autogenerate de este repo propone siempre
borrar 3 índices CONCURRENTLY que sí hacen falta (falso positivo conocido).

Revision ID: a1t11podio
Revises: d6b9f4a37c28
"""
import sqlalchemy as sa
from alembic import op

revision = "a1t11podio"
down_revision = "d6b9f4a37c28"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_tasks_podio_item_id", table_name="tasks")
    op.drop_column("tasks", "podio_item_id")


def downgrade():
    op.add_column("tasks", sa.Column("podio_item_id", sa.String(), nullable=True))
    op.create_index("ix_tasks_podio_item_id", "tasks", ["podio_item_id"])
