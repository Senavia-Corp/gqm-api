from sqlmodel import SQLModel, Field
from typing import Optional


class SupplierBase(SQLModel):

    Company_Name: str
    Company_Website: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Acc_Status: Optional[str] = Field(default=None)
    Acc_Rep: Optional[str] = Field(default=None)
    Speciality: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Coverage_Area: Optional[str] = Field(default=None)
    Phone_Number: Optional[int] = Field(default=None)
    Address: Optional[str] = Field(default=None)


class Supplier(SupplierBase, table=True):
    __tablename__ = "supplier"
    # ID opcional porque Postgre le puede dar un id si la persona no lo digita.
    ID_Supplier: Optional[int] = Field(default=None, primary_key=True)
    # AQUI VAN LAS RELACIONES----------


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(SQLModel):
    Company_Name: Optional[str] = Field(default=None)
    Company_Website: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Acc_Status: Optional[str] = Field(default=None)
    Acc_Rep: Optional[str] = Field(default=None)
    Speciality: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Coverage_Area: Optional[str] = Field(default=None)
    Phone_Number: Optional[int] = Field(default=None)
    Address: Optional[str] = Field(default=None)
