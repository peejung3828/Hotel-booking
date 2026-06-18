import hashlib
import hmac
import json
import base64
from fastapi import APIRouter, Request, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.user import AdminUser
from backend.models.booking import Booking
from backend.services.line_service import LineService

router = APIRouter()


def verify_line_signature(body: bytes, signature: str) -> bool:
    hash_ = hmac.new(
        settings.LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def get_user_role(line_id: str, db: AsyncSession) -> str:
    result = await db.execute(
        select(AdminUser).where(AdminUser.line_id == line_id, AdminUser.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        return "customer"
    return user.role


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(None),
):
    body = await request.body()

    if settings.LINE_CHANNEL_SECRET:
        if not x_line_signature or not verify_line_signature(body, x_line_signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    line_service = LineService()

    async with AsyncSessionLocal() as db:
        for event in data.get("events", []):
            await handle_event(event, db, line_service)

    return {"status": "ok"}


async def handle_event(event: dict, db: AsyncSession, line_service: LineService):
    event_type = event.get("type")
    source = event.get("source", {})
    line_id = source.get("userId", "")
    reply_token = event.get("replyToken")

    role = await get_user_role(line_id, db)

    if event_type == "follow":
        await line_service.send_welcome(reply_token, role)
        return

    if event_type == "message":
        msg = event.get("message", {})
        if msg.get("type") == "text":
            text = msg.get("text", "").strip()
            await handle_text(text, reply_token, line_id, role, db, line_service)

    if event_type == "postback":
        data_str = event.get("postback", {}).get("data", "")
        await handle_postback(data_str, reply_token, line_id, role, db, line_service)


async def handle_text(
    text: str,
    reply_token: str,
    line_id: str,
    role: str,
    db: AsyncSession,
    line_service: LineService,
):
    if text in ("ดูห้อง", "ห้องว่าง", "จองห้อง"):
        from sqlalchemy import and_
        from sqlalchemy.orm import selectinload
        from backend.models.room import Room
        rooms_result = await db.execute(
            select(Room)
            .options(selectinload(Room.images))
            .where(and_(Room.is_active == True, Room.status == "available"))
            .limit(10)
        )
        rooms = rooms_result.scalars().all()
        await line_service.reply_room_type_carousel(reply_token, rooms)
        return

    if text in ("การจอง", "ประวัติการจอง"):
        liff_url = f"https://liff.line.me/{settings.LIFF_ID}?page=history"
        await line_service.reply_text(reply_token, f"ดูประวัติการจองได้ที่: {liff_url}")
        return

    if text.upper().startswith("BK-"):
        result = await db.execute(
            select(Booking).where(Booking.booking_ref == text.upper())
        )
        booking = result.scalar_one_or_none()
        if booking:
            await line_service.reply_booking_detail(reply_token, booking, role)
        else:
            await line_service.reply_text(reply_token, f"ไม่พบการจอง {text}")
        return

    if role in ("admin", "super_admin"):
        if text == "เช็คอินวันนี้":
            from datetime import date
            from sqlalchemy import and_
            result = await db.execute(
                select(Booking).where(
                    and_(Booking.check_in == date.today(), Booking.status == "confirmed")
                )
            )
            bookings = result.scalars().all()
            await line_service.reply_checkin_list(reply_token, bookings)
            return

    await line_service.reply_text(reply_token, "พิมพ์ 'ดูห้อง' เพื่อเลือกห้อง หรือ 'การจอง' เพื่อดูประวัติ")


async def handle_postback(
    data_str: str,
    reply_token: str,
    line_id: str,
    role: str,
    db: AsyncSession,
    line_service: LineService,
):
    if not data_str:
        return

    if data_str.startswith("view_images:"):
        from sqlalchemy import and_
        from sqlalchemy.orm import selectinload
        from backend.models.room import Room
        room_type = data_str.split(":", 1)[1]
        rooms_result = await db.execute(
            select(Room)
            .options(selectinload(Room.images))
            .where(and_(Room.is_active == True, Room.type == room_type))
        )
        rooms = rooms_result.scalars().all()
        await line_service.reply_room_type_images(reply_token, room_type, rooms)
        return

    try:
        params = dict(item.split("=") for item in data_str.split("&"))
    except Exception:
        return

    action = params.get("action")
    booking_ref = params.get("ref")

    if not booking_ref:
        return

    result = await db.execute(select(Booking).where(Booking.booking_ref == booking_ref))
    booking = result.scalar_one_or_none()

    if not booking:
        await line_service.reply_text(reply_token, "ไม่พบการจอง")
        return

    if role not in ("admin", "super_admin"):
        await line_service.reply_text(reply_token, "ไม่มีสิทธิ์ดำเนินการ")
        return

    if action == "confirm_booking" and booking.status == "pending":
        booking.status = "confirmed"
        await db.commit()
        await line_service.reply_text(reply_token, f"✅ ยืนยันการจอง {booking_ref} แล้ว")
        await line_service.push_booking_confirmed(booking)

    elif action == "reject_booking" and booking.status == "pending":
        booking.status = "cancelled"
        await db.commit()
        await line_service.reply_text(reply_token, f"❌ ปฏิเสธการจอง {booking_ref} แล้ว")

    elif action == "checkin" and booking.status == "confirmed":
        booking.status = "checked_in"
        await db.commit()
        await line_service.reply_text(reply_token, f"✅ เช็คอิน {booking_ref} แล้ว")

    elif action == "checkout" and booking.status == "checked_in":
        booking.status = "checked_out"
        await db.commit()
        await line_service.reply_text(reply_token, f"✅ เช็คเอาต์ {booking_ref} แล้ว")
        await line_service.push_review_request(booking)
    else:
        await line_service.reply_text(reply_token, "ไม่สามารถดำเนินการได้")
