from sqlmodel import SQLModel, Field


class JobPaymentULink(SQLModel, table=True):
    __tablename__ = "job_payment_unit"

    job_id: str = Field(
        foreign_key="jobs.ID_Jobs",
        primary_key=True
    )

    payment_unit_id: str = Field(
        foreign_key="payment_unit.ID_PaymentU",
        primary_key=True
    )
