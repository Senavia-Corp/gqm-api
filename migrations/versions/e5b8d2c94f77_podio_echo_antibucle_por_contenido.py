"""podio_echo: el anti-bucle deja de decidir por reloj y decide por contenido

`recent_events` era un diccionario EN MEMORIA con una ventana de 15 segundos,
y descartaba por ítem y por tiempo. Dos fallos, los dos medidos (G4):

1. **No distinguía el eco de la app de una edición humana.** Reproducido: la app
   escribe, se esperan 3 s, alguien corrige un campo en Podio → se perdía sin
   error, sin aviso y sin entrada en la cola de fallos. El receptor respondía
   `200 {"status":"ignored"}` y quien lo escribió veía su número en Podio.
2. **Vivía en la memoria del proceso.** En Vercel cada entrega puede caer en otra
   lambda, así que ni siquiera cumplía su cometido de forma fiable: a veces la
   edición se perdía y a veces no. Es la forma exacta de un «a veces no se
   actualiza».

Esta tabla guarda, por cada escritura saliente, QUÉ campos se escribieron y una
huella de sus valores. El evento entrante se descarta sólo si reproduce
exactamente ese subconjunto. Una edición humana cambia el contenido, así que
entra.

La tabla es de usar y tirar: las filas viejas no molestan (la consulta filtra
por `created_at`), pero conviene una purga periódica.

Revision ID: e5b8d2c94f77
Revises: d4a7c1f38b44
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'e5b8d2c94f77'
down_revision = 'd4a7c1f38b44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'podio_echo',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('item_id', sa.String(), nullable=False),
        sa.Column('claves', sa.String(), nullable=False, server_default=''),
        sa.Column('huella', sa.String(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_podio_echo_item_id', 'podio_echo', ['item_id'])
    op.create_index('ix_podio_echo_huella', 'podio_echo', ['huella'])
    # El índice compuesto es el que sirve la consulta real (ítem + ventana).
    op.create_index('ix_podio_echo_item_created', 'podio_echo', ['item_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_podio_echo_item_created', table_name='podio_echo')
    op.drop_index('ix_podio_echo_huella', table_name='podio_echo')
    op.drop_index('ix_podio_echo_item_id', table_name='podio_echo')
    op.drop_table('podio_echo')
