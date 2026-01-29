from sqlmodel import SQLModel, Field


class PurchaseSupplierLink(SQLModel, table=True):
    __tablename__ = "purchase_supplier"

    purchase_id: str = Field(
        foreign_key="purchase.ID_Purchase",
        primary_key=True
    )

    supplier_id: str = Field(
        foreign_key="supplier.ID_Supplier",
        primary_key=True
    )
