import uuid
from datetime import datetime
from sqlalchemy import String, Text, Numeric, Integer, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(
        SAEnum("deluxe", "superior", "suite", "family", name="room_type"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text)
    price_per_night: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    price_weekend: Mapped[float | None] = mapped_column(Numeric(10, 2))
    price_holiday: Mapped[float | None] = mapped_column(Numeric(10, 2))
    max_guests: Mapped[int] = mapped_column(Integer, default=2)
    min_stay: Mapped[int] = mapped_column(Integer, default=1)
    amenities: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        SAEnum("available", "maintenance", "closed", name="room_status"),
        default="available",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    images: Mapped[list["RoomImage"]] = relationship("RoomImage", back_populates="room", cascade="all, delete-orphan")
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="room")


class RoomImage(Base):
    __tablename__ = "room_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_cover: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    room: Mapped["Room"] = relationship("Room", back_populates="images")
