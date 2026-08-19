"""Traslada Payment_1/2/3 de PAR a order_payment

Las únicas cuotas que hoy existen en la base son las de PAR: 29 órdenes con
`Payment_1`, 6 con `Payment_2`, 0 con `Payment_3` (producción, 18-ago-2026).
Todas tienen `tech_field`, así que se les puede resolver el hueco de Podio.

El mapa PAR va **copiado literal** aquí dentro, no importado de
`payment_slots.py`: una migración que importa código de aplicación se rompe
cuando ese código evoluciona. Son doce cadenas.

El `JOIN` con `jobs` filtrando `Job_type = 'PAR'` hace que sea correcto **por
construcción** y no por coincidencia de datos: los mismos `tech_field`
(`tech-1-ptl-original-pricing`…) los comparten QID y PTL.

Idempotente y reanudable por el `NOT EXISTS`.

Revision ID: d4a7c1f38b44
Revises: c3f6b9e27a33
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'd4a7c1f38b44'
down_revision = 'c3f6b9e27a33'
branch_labels = None
depends_on = None

# (tech_field de la orden, nº de cuota, external_id del hueco) para PAR.
MAPA_PAR = [
    ('tech-1-ptl-original-pricing', 1, 'check-amount-payment-1'),
    ('tech-1-ptl-original-pricing', 2, 'check-amount-payment-2'),
    ('tech-1-ptl-original-pricing', 3, 'check-amount-payment-3'),
    ('tech-2-ptl-original-pricing', 1, 'check-amount-payment-1-2'),
    ('tech-2-ptl-original-pricing', 2, 'check-amount-payment-2-2'),
    ('tech-2-ptl-original-pricing', 3, 'check-amount-payment-3-2'),
    ('tech-3-formula', 1, 'tech-3-payment-1'),
    ('tech-3-formula', 2, 'tech-3-payment-2'),
    ('tech-4-formula', 1, 'tech-4-payment-1'),
    ('tech-4-formula', 2, 'tech-4-payment-2'),
]

VALORES = ", ".join(f"('{tf}', {c}, '{e}')" for tf, c, e in MAPA_PAR)

SQL = f"""
WITH mapa(tech_field, cuota, ext) AS (VALUES {VALORES}),
pares AS (
  SELECT o."ID_Order", o.job_podio_id, v.cuota, v.importe, m.ext,
         row_number() OVER (ORDER BY o."ID_Order", v.cuota) AS n
    FROM "order" o
    JOIN jobs j ON j.podio_item_id = o.job_podio_id AND j."Job_type" = 'PAR'
   CROSS JOIN LATERAL (VALUES (1, o."Payment_1"), (2, o."Payment_2"), (3, o."Payment_3"))
              AS v(cuota, importe)
    LEFT JOIN mapa m ON m.tech_field = o.tech_field AND m.cuota = v.cuota
   WHERE v.importe IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM order_payment op
                      WHERE op."ID_Order" = o."ID_Order" AND op."Installment" = v.cuota)
)
INSERT INTO order_payment
       ("ID_OrderPayment", "ID_Order", "Installment", "Amount",
        job_podio_id, podio_field, created_at, updated_at)
SELECT 'OPY' || substr(EXTRACT(year FROM now())::text, 4, 1)
            || lpad(n::text, 4, '0'),
       "ID_Order", cuota, importe, job_podio_id, ext, now(), now()
  FROM pares
"""


def upgrade() -> None:
    conn = op.get_bind()
    n = conn.execute(sa.text(SQL)).rowcount
    sin_hueco = conn.execute(sa.text(
        'SELECT count(*) FROM order_payment WHERE podio_field IS NULL')).scalar()
    print(f"[cuotas] {n} trasladadas desde Payment_1/2/3 · {sin_hueco} sin hueco "
          f"resoluble (tech_field fuera del mapa PAR)")


def downgrade() -> None:
    conn = op.get_bind()
    altas = conn.execute(sa.text(
        'SELECT count(*) FROM order_payment WHERE "Installment" > 3')).scalar()
    if altas:
        raise RuntimeError(
            f"Hay {altas} cuotas por encima de la 3: `order.Payment_1/2/3` no "
            f"puede guardarlas y revertir las perdería.")
    conn.execute(sa.text('DELETE FROM order_payment WHERE "Installment" <= 3'))
