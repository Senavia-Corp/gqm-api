"""Contadores de los IDs con prefijo (ATT, ORD, TLA, EST, …).

Sustituye al `SELECT max(...)` en Python de `generate_custom_id`, que era un
check-then-act: dos peticiones simultaneas leian el mismo maximo y proponian el
mismo ID. Medido en DEV el 21-ago-2026 con N sesiones a la vez:

    2 sesiones -> 0 colisiones     5 sesiones -> 3 colisiones (60% perdido)
    3 sesiones -> 1 colision       8 sesiones -> 6 colisiones (75% perdido)

El techo real eran ~2 inserciones concurrentes.

POR QUE UNA TABLA Y NO UNA SECUENCIA DE POSTGRES
------------------------------------------------
Una secuencia por prefijo seria mas idiomatico, pero son ~30 objetos que crear
y sembrar, y sobre todo **el cambio de digito de año se vuelve una tarea manual
anual sobre 30 objetos**. Este repo ya perdio 88 dias de auditoria por un caso
borde del contador que nadie miro (ver 1bb0de7). No se pone nada que dependa de
que alguien se acuerde cada 1 de enero.

Con esta tabla el cambio de año es automatico: el 1-ene-2027 el UPDATE afecta
0 filas para ('ATT','7'), se siembra desde cero y sale ATT70001. Igual que hoy,
sin intervencion.

POR QUE NO UN ADVISORY LOCK
---------------------------
`pg_advisory_xact_lock` se libera al COMMIT de la transaccion que lo tomo, no
al salir de generate_custom_id. Y la transaccion del webhook de adjuntos
contiene dos `requests.get` a Podio y una subida a Cloudinary: seria un lock
global de escritura retenido segundos, y sin timeout, indefinidamente si Podio
se cuelga. La primitiva correcta en el sitio equivocado.

Aqui el row lock del UPDATE dura UNA SENTENCIA, en una conexion aparte que
commitea al instante, asi que no depende de cuanto dure la transaccion del
llamador.

OJO: el acceso real se hace por SQL crudo desde `src/utils/id_generator.py`,
no por este modelo. El modelo existe para que la tabla este en
`SQLModel.metadata` — sin el, el proximo `alembic revision --autogenerate`
propondria `op.drop_table('id_counters')`.
"""
from typing import Optional

from sqlmodel import Field, SQLModel


class IdCounter(SQLModel, table=True):
    __tablename__ = "id_counters"

    # PK compuesta: un contador por (prefijo, digito de año).
    prefix: str = Field(primary_key=True, max_length=16)
    year_digit: str = Field(primary_key=True, max_length=1)
    last_value: int = Field(default=0, nullable=False)
