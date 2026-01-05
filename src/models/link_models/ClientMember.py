from sqlmodel import SQLModel, Field
from typing import Optional


class ClientMemberLink(SQLModel, table=True):
    __tablename__ = "client_member"

    clients_id: str = Field(
        foreign_key="client.ID_Client",
        primary_key=True
    )

    members_id: str = Field(
        foreign_key="member.ID_Member",
        primary_key=True
    )

    rol: Optional[str] = Field(default=None)
