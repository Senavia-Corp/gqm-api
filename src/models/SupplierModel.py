
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field
from typing import Optional


class SupplierBase(SQLModel):

    Company_Name: str
    Company_Website: str
    Description: Optional[str] = Field(default=None)
    Acc_Status: str
    Acc_Rep: str
    Speciality: Optional[str] = Field(default=None)
    Email_Address: str
    Coverage_Area: str
    Phone_Number: str
    Address: Optional[str] = Field(default=None)


class Supplier(SupplierBase, table=True):
    __tablename__ = "supplier"

    ID_Supplier: Optional[str] = Field(default=None, primary_key=True)


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(SupplierBase):
    Company_Name: Optional[str] = Field(default=None)
    Company_Website: Optional[str] = Field(default=None)
    Acc_Status: Optional[str] = Field(default=None)
    Acc_Rep: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Coverage_Area: Optional[str] = Field(default=None)
    Phone_Number: Optional[str] = Field(default=None)
