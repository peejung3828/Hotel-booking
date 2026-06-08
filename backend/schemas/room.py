import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class RoomImageOut(BaseModel):
    id: uuid.UUID
    url: str
    is_cover: bool
    sort_order: int

    model_config = {"from_attributes": True}


class RoomBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(..., pattern="^(deluxe|superior|suite|family)$")
    description: str | None = None
    price_per_night: float = Field(..., gt=0)
    price_weekend: float | None = None
    price_holiday: float | None = None
    max_guests: int = Field(2, ge=1, le=20)
    min_stay: int = Field(1, ge=1)
    amenities: dict[str, Any] = {}
    status: str = Field("available", pattern="^(available|maintenance|closed)$")
    is_active: bool = True


class RoomCreate(RoomBase):
    pass


class RoomUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    price_per_night: float | None = None
    price_weekend: float | None = None
    price_holiday: float | None = None
    max_guests: int | None = None
    min_stay: int | None = None
    amenities: dict[str, Any] | None = None
    status: str | None = None
    is_active: bool | None = None


class RoomOut(RoomBase):
    id: uuid.UUID
    images: list[RoomImageOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoomAvailableQuery(BaseModel):
    check_in: str
    check_out: str
    guests: int = 1
