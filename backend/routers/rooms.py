import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, not_, exists
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.room import Room, RoomImage
from backend.models.booking import Booking
from backend.models.line_config import BlockedDate
from backend.schemas.room import RoomCreate, RoomUpdate, RoomOut
from backend.routers.auth import require_admin

router = APIRouter()


@router.get("", response_model=list[RoomOut])
async def list_rooms(
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Room).options(selectinload(Room.images))
    if is_active is not None:
        stmt = stmt.where(Room.is_active == is_active)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/available", response_model=list[RoomOut])
async def get_available_rooms(
    check_in: str = Query(...),
    check_out: str = Query(...),
    guests: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    try:
        ci = date.fromisoformat(check_in)
        co = date.fromisoformat(check_out)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format, use YYYY-MM-DD")

    if ci >= co:
        raise HTTPException(status_code=422, detail="check_out must be after check_in")

    # Check for blocked dates
    blocked = await db.execute(
        select(BlockedDate).where(BlockedDate.date >= ci, BlockedDate.date < co)
    )
    if blocked.scalars().first():
        return []

    # Rooms with no overlapping confirmed/checked_in bookings
    overlapping_booking = (
        select(Booking.room_id)
        .where(
            and_(
                Booking.status.in_(["confirmed", "checked_in", "pending"]),
                Booking.check_in < co,
                Booking.check_out > ci,
            )
        )
    )

    stmt = (
        select(Room)
        .options(selectinload(Room.images))
        .where(
            Room.is_active == True,
            Room.status == "available",
            Room.max_guests >= guests,
            not_(Room.id.in_(overlapping_booking)),
        )
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{room_id}", response_model=RoomOut)
async def get_room(room_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Room).options(selectinload(Room.images)).where(Room.id == room_id)
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.post("", response_model=RoomOut)
async def create_room(
    data: RoomCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    room = Room(**data.model_dump())
    db.add(room)
    await db.commit()
    result = await db.execute(
        select(Room).options(selectinload(Room.images)).where(Room.id == room.id)
    )
    return result.scalar_one()


@router.put("/{room_id}", response_model=RoomOut)
async def update_room(
    room_id: uuid.UUID,
    data: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(room, field, value)

    await db.commit()
    result = await db.execute(
        select(Room).options(selectinload(Room.images)).where(Room.id == room_id)
    )
    return result.scalar_one()


@router.delete("/{room_id}")
async def delete_room(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    await db.delete(room)
    await db.commit()
    return {"message": "Room deleted"}
