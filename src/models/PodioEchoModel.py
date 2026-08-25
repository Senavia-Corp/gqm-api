"""Huella de lo que la app acaba de escribir en Podio, para descartar su eco.

Sustituye a `recent_events`, un diccionario **en memoria** con una ventana de
15 segundos. Tenía dos fallos, los dos medidos:

1. **Descartaba por ítem y por reloj, no por contenido**, así que no distinguía
   el eco de la app de una edición humana. Reproducido: la app escribe, se
   esperan 3 s, alguien edita otro campo en Podio → se perdía sin error, sin
   aviso y sin entrada en la cola de fallos; el receptor respondía
   `200 {"status":"ignored"}` y quien lo escribió veía su número en Podio.
2. **Vivía en la memoria del proceso.** En Vercel cada entrega puede caer en
   otra lambda, así que ni siquiera cumplía su cometido de forma fiable: a
   veces la edición se perdía y a veces no. Es la forma exacta de un «a veces
   no se actualiza».

Ahora se guarda la huella de los campos escritos, y sólo se descarta lo que
vuelve **idéntico**. Una edición humana cambia el contenido, así que entra.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, TIMESTAMP, func
from sqlmodel import Field, SQLModel


class PodioEcho(SQLModel, table=True):
    __tablename__ = "podio_echo"

    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: str = Field(index=True)
    # Los `external_id` que la app escribió, separados por coma. Hacen falta
    # para poder recortar el ítem entrante a ESOS campos antes de comparar: el
    # eco vuelve con el ítem completo, no con el subconjunto que escribimos.
    claves: str = Field(default="")
    # sha256 de los pares (external_id, valor) que la app acabó de escribir.
    huella: str = Field(index=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(),
                         nullable=False, index=True))
