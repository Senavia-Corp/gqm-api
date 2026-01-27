from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional


class QuickBooksToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    realm_id: str = Field(index=True)

    access_token: str
    refresh_token: str
    token_type: Optional[str] = None

    expires_in: int = 3600
    refresh_token_expires_in: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
