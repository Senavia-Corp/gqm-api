"""tabla id_counters — contadores de IDs con prefijo

Revision ID: c5a8e3f24b17
Revises: b4f7c2e18d09
Create Date: 2026-08-21 17:40:00.000000

Migracion ADITIVA y de bajo riesgo: crea UNA TABLA VACIA y no toca ninguna
existente. No hay sembrado en el cutover, no hay ventana, no hay orden critico
frente a otras migraciones. El codigo que la usa llega en la migracion
siguiente (paso 4); mientras tanto la tabla simplemente esta ahi sin que nadie
la lea.

PARA QUE
--------
Sustituye al `SELECT max(...)` en Python de `generate_custom_id`, que es un
check-then-act sin lock: dos peticiones simultaneas leen el mismo maximo y
proponen el mismo ID. Medido en DEV: con 3 sesiones a la vez se pierde el 33%,
con 8 el 75%. El techo real son ~2 inserciones concurrentes, y afecta a los
~30 prefijos (ATT, ORD, EST, TLA, FD, …), no solo a los adjuntos.

SEMBRADO PEREZOSO — no hace falta rellenarla aqui
--------------------------------------------------
La tabla nace vacia a proposito. La primera vez que se pida un ID de un par
(prefijo, digito de año), el UPDATE afecta 0 filas y el codigo siembra ese
contador desde el maximo actual de la tabla real, una sola vez en toda su vida.

Efecto util: el cambio de digito de año es automatico. El 1-ene-2027 el UPDATE
de ('ATT','7') afecta 0 filas, se siembra desde 0 y sale ATT70001 — igual que
hoy, sin que nadie tenga que acordarse. Eso es lo que descarta las ~30
secuencias de Postgres: alli el rollover seria una tarea manual anual sobre 30
objetos, y este repo ya perdio 88 dias de auditoria por un caso borde del
contador que nadie miro (1bb0de7).

ROLLBACK
--------
Seguro en los dos sentidos. La tabla es invisible para el codigo actual, asi
que se puede aplicar hoy y desplegar el codigo despues, o volver atras sin
consecuencias: el algoritmo viejo de max+1 sigue siendo consistente (como
mucho reutiliza un hueco quemado, nunca colisiona).

ESCRITA A MANO, NO CON AUTOGENERATE
------------------------------------
`alembic revision --autogenerate` propone borrar CINCO indices reales de
produccion que no estan declarados en los modelos SQLModel (los cuatro de
c3b8d5a1f740 mas ux_attachments_podio_file_id de b4f7c2e18d09). Aceptar su
propuesta destruiria, entre otros, el unico indice que impide que el mismo
fichero de Podio se inserte dos veces.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c5a8e3f24b17'
down_revision: Union[str, Sequence[str], None] = 'b4f7c2e18d09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "id_counters",
        # 16 caracteres sobran: el prefijo mas largo en uso son 6 (BLGDEP).
        sa.Column("prefix", sa.String(length=16), nullable=False),
        # Un solo caracter: es el ULTIMO digito del año (2026 -> "6"), que es
        # justo lo que usa el formato de ID. Cicla cada 10 años, igual que hoy.
        sa.Column("year_digit", sa.String(length=1), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.PrimaryKeyConstraint("prefix", "year_digit"),
    )


def downgrade() -> None:
    op.drop_table("id_counters")
