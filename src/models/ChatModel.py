
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from sqlalchemy import Column, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSON


class ChatMessageBase(SQLModel):
    content: str


class ChatMessage(ChatMessageBase, table=True):
    __tablename__ = "chat_message"

    ID_ChatMessage: Optional[str] = Field(default=None, primary_key=True)

    # Timestamps automáticos
    created_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True),
                         server_default=func.now(), nullable=False)
    )

    ID_Job: str = Field(foreign_key="jobs.ID_Jobs")
    ID_Member: str = Field(foreign_key="member.ID_Member")

    job: Optional["Job"] = Relationship(  # type: ignore
        back_populates="chat_messages")
    member: Optional["Member"] = Relationship(  # type: ignore
        back_populates="chat_messages")
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="chat_message",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})


class ChatMessageCreate(SQLModel):
    content: str


class ChatMessageRead(SQLModel):
    ID_ChatMessage: str
    content: str
    ID_Job: str
    ID_Member: str
    created_at: datetime
    member_name: Optional[str] = None
    attachments: List[dict] = []
