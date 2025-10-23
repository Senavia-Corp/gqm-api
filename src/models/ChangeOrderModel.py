from sqlmodel import SQLModel, Field
from typing import Optional


class ChangeOrder(SQLModel, table=True):
    __tablename__ = "change_order"

    ID_ChangeOrder: Optional[int] = Field(default=None, primary_key=True)
    Name: str
    Description: str
    ChangeOrder_Formula: float = Field(
        default=0.0, alias="ChangeOrder Formula")
    State: str
    ID_JOBS: str

## ------- REVISAR POR CONFLICTO ENTRE SQLMODEL Y ALCHEMY POR RELACION CON JOBS ------- ##
