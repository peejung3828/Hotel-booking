import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.booking import Booking
from backend.schemas.booking import BookingCreate, BookingOut, BookingStatusUpdate
from backend.services.booking_service import BookingService
from backend.services.line_service import LineService
from backend.routers.auth import require_admin

router = APIRouter()


@router.post("", response_model=BookingOut)
async def create_booking(
    data: BookingCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    redis = request.app.state.redis
    service = BookingService(db, redis)
    booking = await service.create_booking(data)

    # Notify admin
    try:
        line_service = LineService()
        await line_service.notify_admin_new_booking(booking)
    except Exception:
        pass

    return booking


@router.get("/customer/{line_id}", response_model=list[BookingOut])
async def get_customer_bookings(line_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Booking)
        .options(selectinload(Booking.room))
        .where(Booking.customer_line_id == line_id)
        .order_by(Booking.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{ref}", response_model=BookingOut)
async def get_booking(ref: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Booking).options(selectinload(Booking.room)).where(Booking.booking_ref == ref)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.put("/{ref}/confirm", response_model=BookingOut)
async def confirm_booking(
    ref: str,
    body: BookingStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Booking).where(Booking.booking_ref == ref))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot confirm booking with status '{booking.status}'")

    booking.status = "confirmed"
    if body.notes:
        booking.notes = body.notes
    await db.commit()
    await db.refresh(booking)

    try:
        line_service = LineService()
        await line_service.push_booking_confirmed(booking)
    except Exception:
        pass

    return booking


@router.put("/{ref}/checkin", response_model=BookingOut)
async def checkin_booking(
    ref: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Booking).where(Booking.booking_ref == ref))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != "confirmed":
        raise HTTPException(status_code=400, detail="Booking must be confirmed before check-in")

    booking.status = "checked_in"
    await db.commit()
    await db.refresh(booking)
    return booking


@router.put("/{ref}/checkout", response_model=BookingOut)
async def checkout_booking(
    ref: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Booking).where(Booking.booking_ref == ref))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != "checked_in":
        raise HTTPException(status_code=400, detail="Booking must be checked-in before check-out")

    booking.status = "checked_out"
    await db.commit()
    await db.refresh(booking)

    try:
        line_service = LineService()
        await line_service.push_review_request(booking)
    except Exception:
        pass

    return booking


@router.put("/{ref}/cancel", response_model=BookingOut)
async def cancel_booking(
    ref: str,
    body: BookingStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Booking).where(Booking.booking_ref == ref))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status in ("checked_in", "checked_out"):
        raise HTTPException(status_code=400, detail="Cannot cancel an active stay")

    booking.status = "cancelled"
    if body.notes:
        booking.notes = body.notes
    await db.commit()
    await db.refresh(booking)
    return booking
