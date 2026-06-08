import uuid
from datetime import datetime, date
from pydantic import BaseModel, Field


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=50)
    discount_type: str = Field(..., pattern="^(percent|fixed)$")
    discount_value: float = Field(..., gt=0)
    max_usage: int = Field(1, ge=1)
    min_order_amount: float | None = None
    start_date: date | None = None
    expire_date: date | None = None
    is_active: bool = True


class CouponUpdate(BaseModel):
    discount_type: str | None = None
    discount_value: float | None = None
    max_usage: int | None = None
    min_order_amount: float | None = None
    start_date: date | None = None
    expire_date: date | None = None
    is_active: bool | None = None


class CouponValidate(BaseModel):
    code: str
    order_amount: float


class CouponOut(BaseModel):
    id: uuid.UUID
    code: str
    discount_type: str
    discount_value: float
    max_usage: int
    used_count: int
    min_order_amount: float | None
    start_date: date | None
    expire_date: date | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CouponValidateResponse(BaseModel):
    valid: bool
    discount_type: str | None = None
    discount_value: float | None = None
    discount_amount: float | None = None
    message: str | None = None
