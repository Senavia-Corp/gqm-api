"""order_payment: las cuotas al técnico dejan de caber en tres columnas

`Order` tenía `Payment_1/2/3`, y el mapa de cuotas sólo cubría PAR. Pero Podio
tiene **11 cuotas para el técnico 1 de QID**, 4 para varios de PTL, y hasta 17
secciones de técnico en QID 2023. Medido en producción: 9.066 órdenes QID con
$0,00 en pagos frente a $41,5 M en fórmulas, mientras Podio sí tiene los cheques.

`Payment_1/2/3` se conservan como **proyección de solo lectura** de las cuotas
1..3 mientras el panel se adapta; el traslado de datos va en `d4a7c1f38b44`.

`ondelete="CASCADE"` no es cosmético: `Webhook_bp.py:399` y `Job.py:1207` borran
órdenes en masa con SQL directo, y una hija sin cascada abortaría el borrado
entero con ForeignKeyViolation.

También añade `order.Podio_check_numbers`, espejo textual del `Check Number(s)`
de la sección — que es **uno por sección**, no uno por cuota. Se lee de Podio y
nunca se escribe.

Revision ID: c3f6b9e27a33
Revises: b2e5c8d16f22
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'c3f6b9e27a33'
down_revision = 'b2e5c8d16f22'
branch_labels = None
depends_on = None

UNICO = 'ux_order_payment_slot'


def upgrade() -> None:
    op.create_table(
        'order_payment',
        sa.Column('ID_OrderPayment', sa.String(), nullable=False),
        sa.Column('ID_Order', sa.String(), nullable=True),
        sa.Column('Installment', sa.Integer(), nullable=True),
        sa.Column('Amount', sa.Float(), nullable=True),
        sa.Column('Date', sa.Date(), nullable=True),
        sa.Column('Check_number', sa.String(), nullable=True),
        sa.Column('podio_field', sa.String(), nullable=True),
        sa.Column('job_podio_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ID_Order'], ['order.ID_Order'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('ID_OrderPayment'),
    )
    op.create_index('ix_order_payment_id_order', 'order_payment', ['ID_Order'])
    op.create_index('ix_order_payment_job_podio_id', 'order_payment', ['job_podio_id'])
    op.create_index('ix_order_payment_podio_field', 'order_payment', ['podio_field'])

    op.add_column('order', sa.Column('Podio_check_numbers', sa.String(), nullable=True))

    with op.get_context().autocommit_block():
        op.execute(
            f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {UNICO} '
            f'ON order_payment ("ID_Order", podio_field) WHERE podio_field IS NOT NULL')


def downgrade() -> None:
    # Punto de no retorno: las cuotas 4..11 no tienen dónde volver. Sólo se
    # puede revertir mientras `Payment_1/2/3` siga siendo el espejo completo.
    conn = op.get_bind()
    altas = conn.execute(sa.text(
        'SELECT count(*) FROM order_payment WHERE "Installment" > 3')).scalar()
    if altas:
        raise RuntimeError(
            f"Hay {altas} cuotas por encima de la 3 que `order.Payment_1/2/3` no "
            f"puede guardar: revertir las perdería. Expórtalas antes, o borra "
            f"esas filas a conciencia.")

    with op.get_context().autocommit_block():
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {UNICO}')
    op.drop_column('order', 'Podio_check_numbers')
    op.drop_index('ix_order_payment_podio_field', table_name='order_payment')
    op.drop_index('ix_order_payment_job_podio_id', table_name='order_payment')
    op.drop_index('ix_order_payment_id_order', table_name='order_payment')
    op.drop_table('order_payment')
