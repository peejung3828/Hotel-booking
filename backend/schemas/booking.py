import uuid
from datetime import datetime, date
from pydantic import BaseModel, Field


class BookingCreate(BaseModel):
    room_id: uuid.UUID
    customer_line_id: str
    customer_name: str = Field(..., min_length=1, max_length=200)
    customer_phone: str = Field(..., min_length=9, max_length=20)
    check_in: date
    check_out: date
    coupon_code: str | None = None
    notes: str | None = None


class BookingOut(BaseModel):
    id: uuid.UUID
    booking_ref: str
    room_id: uuid.UUID
    customer_line_id: str
    customer_name: str
    customer_phone: str
    check_in: date
    check_out: date
    nights: int
    base_price: float
    discount_amount: float
    total_price: float
    coupon_code: str | None
    room_name: str | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BookingStatusUpdate(BaseModel):
    notes: str | None = None
