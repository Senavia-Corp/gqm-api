from sqlmodel import SQLModel, Field
from typing import Optional
from sqlalchemy import Column, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime

class PodioFailedSyncBase(SQLModel):
    item_id: Optional[str] = Field(default=None, index=True)
    hook_type: Optional[str] = Field(default=None)
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error_message: Optional[str] = Field(default=None)
    resolved: bool = Field(default=False)

class PodioFailedSync(PodioFailedSyncBase, table=True):
    __tablename__ = "podio_failed_syncs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    
    created_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
