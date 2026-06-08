from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
import redis.asyncio as aioredis

from backend.models.booking import Booking
from backend.models.room import Room
from backend.models.coupon import Coupon
from backend.models.line_config import BlockedDate
from backend.schemas.booking import BookingCreate


class RoomNotAvailableError(Exception):
    pass


class BookingService:
    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def _generate_booking_ref(self) -> str:
        year = datetime.utcnow().year
        key = f"booking_seq:{year}"
        seq = await self.redis.incr(key)
        # Expire at end of year
        await self.redis.expireat(key, int(datetime(year + 1, 1, 1).timestamp()))
        return f"BK-{year}-{seq:04d}"

    async def _acquire_lock(self, room_id: str, check_in: date, check_out: date) -> str:
        lock_key = f"lock:room:{room_id}:{check_in}:{check_out}"
        acquired = await self.redis.set(lock_key, "1", nx=True, ex=30)
        if not acquired:
            raise RoomNotAvailableError("Room is being booked by someone else. Please try again.")
        return lock_key

    async def _release_lock(self, lock_key: str):
        await self.redis.delete(lock_key)

    async def create_booking(self, data: BookingCreate) -> Booking:
        ci: date = data.check_in
        co: date = data.check_out

        if ci >= co:
            raise ValueError("check_out must be after check_in")
        if ci < date.today():
            raise ValueError("check_in cannot be in the past")

        # Check blocked dates
        blocked = await self.db.execute(
            select(BlockedDate).where(BlockedDate.date >= ci, BlockedDate.date < co)
        )
        if blocked.scalars().first():
            raise RoomNotAvailableError("Selected dates are blocked")

        # Check room exists and is active
        room_result = await self.db.execute(
            select(Room).where(Room.id == data.room_id, Room.is_active == True, Room.status == "available")
        )
        room = room_result.scalar_one_or_none()
        if not room:
            raise RoomNotAvailableError("Room is not available")

        if room.min_stay > (co - ci).days:
            raise ValueError(f"Minimum stay is {room.min_stay} night(s)")

        # Acquire Redis lock
        lock_key = await self._acquire_lock(str(data.room_id), ci, co)

        try:
            # Double-check availability (within lock)
            overlap = await self.db.execute(
                select(Booking).where(
                    and_(
                        Booking.room_id == data.room_id,
                        Booking.status.in_(["pending", "confirmed", "checked_in"]),
                        Booking.check_in < co,
                        Booking.check_out > ci,
                    )
                )
            )
            if overlap.scalars().first():
                raise RoomNotAvailableError("Room is already booked for these dates")

            nights = (co - ci).days
            base_price = await self._calculate_price(room, ci, co)
            discount_amount = 0.0

            # Apply coupon
            if data.coupon_code:
                coupon_result = await self.db.execute(
                    select(Coupon).where(
                        Coupon.code == data.coupon_code.upper(),
                        Coupon.is_active == True,
                    )
                )
                coupon = coupon_result.scalar_one_or_none()
                today = date.today()
                if (
                    coupon
                    and coupon.used_count < coupon.max_usage
                    and (not coupon.start_date or today >= coupon.start_date)
                    and (not coupon.expire_date or today <= coupon.expire_date)
                    and (not coupon.min_order_amount or base_price >= float(coupon.min_order_amount))
                ):
                    if coupon.discount_type == "percent":
                        discount_amount = base_price * (coupon.discount_value / 100)
                    else:
                        discount_amount = min(coupon.discount_value, base_price)
                    coupon.used_count += 1

            total_price = max(0, base_price - discount_amount)
            booking_ref = await self._generate_booking_ref()

            booking = Booking(
                booking_ref=booking_ref,
                room_id=data.room_id,
                customer_line_id=data.customer_line_id,
                customer_name=data.customer_name,
                customer_phone=data.customer_phone,
                check_in=ci,
                check_out=co,
                nights=nights,
                base_price=base_price,
                discount_amount=round(discount_amount, 2),
                total_price=round(total_price, 2),
                coupon_code=data.coupon_code,
                notes=data.notes,
                status="pending",
            )

            self.db.add(booking)
            await self.db.commit()
            await self.db.refresh(booking)
            return booking

        finally:
            await self._release_lock(lock_key)

    async def _calculate_price(self, room: Room, check_in: date, check_out: date) -> float:
        from datetime import timedelta
        total = 0.0
        current = check_in
        while current < check_out:
            weekday = current.weekday()
            if weekday >= 5 and room.price_weekend:  # Sat/Sun
                total += float(room.price_weekend)
            else:
                total += float(room.price_per_night)
            current += timedelta(days=1)
        return total
