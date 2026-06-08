from datetime import date, datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, and_, func
import redis.asyncio as aioredis

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.booking import Booking
from backend.models.payment import Payment
from backend.models.room import Room
from backend.models.user import AdminUser
from backend.services.line_service import LineService

scheduler = AsyncIOScheduler(timezone="Asia/Bangkok")


async def _get_redis() -> aioredis.Redis:
    return await aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)


async def daily_summary_job():
    """Send daily summary to super admins at 09:00."""
    today = date.today()
    async with AsyncSessionLocal() as db:
        revenue = await db.execute(
            select(func.sum(Payment.amount)).where(
                and_(func.date(Payment.created_at) == today, Payment.status == "verified")
            )
        )
        new_bookings = await db.execute(
            select(func.count(Booking.id)).where(func.date(Booking.created_at) == today)
        )
        checkins = await db.execute(
            select(func.count(Booking.id)).where(
                and_(Booking.check_in == today, Booking.status.in_(["confirmed", "checked_in"]))
            )
        )
        checkouts = await db.execute(
            select(func.count(Booking.id)).where(
                and_(Booking.check_out == today, Booking.status == "checked_out")
            )
        )
        available_rooms = await db.execute(
            select(func.count(Room.id)).where(and_(Room.status == "available", Room.is_active == True))
        )
        super_admins = await db.execute(
            select(AdminUser).where(and_(AdminUser.role == "super_admin", AdminUser.is_active == True))
        )

        stats = {
            "date": str(today),
            "revenue": float(revenue.scalar() or 0),
            "new_bookings": new_bookings.scalar() or 0,
            "checkins": checkins.scalar() or 0,
            "checkouts": checkouts.scalar() or 0,
            "available_rooms": available_rooms.scalar() or 0,
        }

        line_service = LineService()
        for admin in super_admins.scalars().all():
            if admin.line_id:
                await line_service.push_daily_summary(admin.line_id, stats)


async def checkin_reminder_job():
    """Send check-in reminder 24 hours before — once per booking via Redis dedup."""
    tomorrow = date.today() + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Booking).where(
                and_(Booking.check_in == tomorrow, Booking.status == "confirmed")
            )
        )
        bookings = result.scalars().all()

    if not bookings:
        return

    redis = await _get_redis()
    line_service = LineService()
    try:
        for booking in bookings:
            key = f"checkin_reminded:{booking.id}"
            already_sent = await redis.exists(key)
            if not already_sent:
                await line_service.push_checkin_reminder(booking)
                await redis.set(key, "1", ex=90000)  # 25-hour TTL
    finally:
        await redis.aclose()


async def payment_timeout_job():
    """Cancel pending bookings with no active payment after 30 minutes."""
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Booking).where(
                and_(
                    Booking.status == "pending",
                    Booking.created_at < cutoff,
                )
            )
        )
        bookings = result.scalars().all()

        for booking in bookings:
            payment_result = await db.execute(
                select(Payment).where(Payment.booking_id == booking.id)
            )
            payments = payment_result.scalars().all()
            # Keep booking alive if any payment is pending or verified
            has_active_payment = any(p.status in ("pending", "verified") for p in payments)
            if not has_active_payment:
                booking.status = "cancelled"
                booking.notes = (booking.notes or "") + " | Auto-cancelled: no payment within 30 minutes"

        await db.commit()


async def checkout_review_job():
    """Send review request 30–60 minutes after checkout."""
    now = datetime.utcnow()
    cutoff_start = now - timedelta(hours=1)
    cutoff_end = now - timedelta(minutes=30)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Booking).where(
                and_(
                    Booking.status == "checked_out",
                    Booking.updated_at >= cutoff_start,
                    Booking.updated_at < cutoff_end,
                )
            )
        )
        bookings = result.scalars().all()

    if not bookings:
        return

    redis = await _get_redis()
    line_service = LineService()
    try:
        for booking in bookings:
            key = f"review_sent:{booking.id}"
            already_sent = await redis.exists(key)
            if not already_sent:
                await line_service.push_review_request(booking)
                await redis.set(key, "1", ex=86400)  # 24-hour TTL
    finally:
        await redis.aclose()


scheduler.add_job(
    daily_summary_job, CronTrigger(hour=9, minute=0, timezone="Asia/Bangkok"),
    id="daily_summary_job", name="Daily Summary",
)
scheduler.add_job(
    checkin_reminder_job, IntervalTrigger(hours=1),
    id="checkin_reminder_job", name="Check-in Reminder",
)
scheduler.add_job(
    payment_timeout_job, IntervalTrigger(minutes=5),
    id="payment_timeout_job", name="Payment Timeout",
)
scheduler.add_job(
    checkout_review_job, IntervalTrigger(minutes=30),
    id="checkout_review_job", name="Checkout Review",
)
