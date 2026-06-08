import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class PaymentCreate(BaseModel):
    booking_id: uuid.UUID
    method: str = Field(..., pattern="^(bank_transfer|qr_promptpay|line_pay|debit_card|credit_card)$")
    amount: float = Field(..., gt=0)
    omise_token: str | None = None  # for card payment


class PaymentSlipUpload(BaseModel):
    payment_id: uuid.UUID
    slip_url: str


class PaymentVerify(BaseModel):
    verified_by: str


class PaymentReject(BaseModel):
    rejection_reason: str


class PaymentOut(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    method: str
    amount: float
    status: str
    slip_url: str | None
    omise_charge_id: str | None
    transaction_id: str | None
    verified_at: datetime | None
    verified_by: str | None
    rejection_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
