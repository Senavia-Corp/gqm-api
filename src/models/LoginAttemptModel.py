from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, Column, func
from sqlmodel import Field, SQLModel


class LoginAttempt(SQLModel, table=True):
    """Intentos de login, para que el rate limit funcione en serverless.

    El limitador original era un dict en memoria del proceso. En Vercel cada
    peticion puede caer en una instancia distinta, asi que ninguna acumulaba lo
    suficiente para frenar nada: verificado el 10-ago-2026 con 12 logins
    fallidos seguidos contra gqm-api-dev — 12 respuestas 401 y ni un 429,
    mientras el mismo bucle en local (proceso unico) frenaba en el intento 21.

    Con la ventana en la BD el conteo es compartido por todas las instancias.
    Las filas son efimeras: cada comprobacion borra las que salen de la ventana.
    """

    __tablename__ = "login_attempt"

    id: Optional[int] = Field(default=None, primary_key=True)

    # "<ip>|<email>" — mismo criterio que el limitador anterior.
    attempt_key: str = Field(index=True, max_length=320, nullable=False)

    created_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        )
    )
