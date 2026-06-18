from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    AsyncApiClient, AsyncMessagingApi,
    Configuration, ReplyMessageRequest, PushMessageRequest,
    TextMessage, FlexMessage, FlexContainer,
)
from linebot.v3.messaging.models import (
    FlexBubble, FlexBox, FlexText, FlexButton, FlexImage,
    URIAction, PostbackAction, MessageAction,
)
from sqlalchemy import select
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.user import AdminUser
from backend.models.booking import Booking
from backend.models.room import Room


class LineService:
    def __init__(self):
        configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
        self.api_client = AsyncApiClient(configuration)
        self.messaging_api = AsyncMessagingApi(self.api_client)

    async def reply_text(self, reply_token: str, text: str):
        if not reply_token or not settings.LINE_CHANNEL_ACCESS_TOKEN:
            return
        await self.messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(type="text", text=text)],
            )
        )

    async def push_text(self, to: str, text: str):
        if not settings.LINE_CHANNEL_ACCESS_TOKEN:
            return
        await self.messaging_api.push_message(
            PushMessageRequest(to=to, messages=[TextMessage(type="text", text=text)])
        )

    async def send_welcome(self, reply_token: str, role: str):
        if role == "super_admin":
            msg = "🏨 ยินดีต้อนรับ Super Admin!\n\nพิมพ์ 'เช็คอินวันนี้' หรือรอรับรายงานประจำวัน"
        elif role == "admin":
            msg = "🏨 ยินดีต้อนรับ Admin!\n\nพิมพ์ 'เช็คอินวันนี้' เพื่อดูรายการเช็คอินวันนี้"
        else:
            msg = (
                "🏨 ยินดีต้อนรับสู่โรงแรมของเรา!\n\n"
                "พิมพ์ 'ดูห้อง' เพื่อเลือกห้องพัก\n"
                "พิมพ์ 'การจอง' เพื่อดูประวัติการจอง\n"
                "หรือกรอกรหัสการจอง เช่น BK-2026-0001"
            )
        await self.reply_text(reply_token, msg)

    async def reply_booking_detail(self, reply_token: str, booking: Booking, role: str):
        bubble = self._build_booking_bubble(booking, include_admin_buttons=(role in ("admin", "super_admin")))
        flex = FlexMessage(
            alt_text=f"การจอง {booking.booking_ref}",
            contents=FlexContainer.from_dict(bubble),
        )
        await self.messaging_api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[flex])
        )

    def _build_booking_bubble(self, booking: Booking, include_admin_buttons: bool = False) -> dict:
        status_emoji = {
            "pending": "⏳", "confirmed": "✅", "checked_in": "🏠",
            "checked_out": "👋", "cancelled": "❌",
        }.get(booking.status, "❓")

        contents = {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1a73e8",
                "contents": [
                    {"type": "text", "text": "🏨 รายละเอียดการจอง", "color": "#ffffff", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": booking.booking_ref, "color": "#ffffff", "size": "sm"},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    self._info_row("สถานะ", f"{status_emoji} {booking.status}"),
                    self._info_row("ชื่อ", booking.customer_name),
                    self._info_row("เช็คอิน", str(booking.check_in)),
                    self._info_row("เช็คเอาต์", str(booking.check_out)),
                    self._info_row("จำนวนคืน", f"{booking.nights} คืน"),
                    self._info_row("ยอดรวม", f"฿{booking.total_price:,.0f}"),
                ],
            },
        }

        if include_admin_buttons and booking.status == "pending":
            contents["footer"] = {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#4CAF50",
                        "action": {
                            "type": "postback",
                            "label": "ยืนยัน",
                            "data": f"action=confirm_booking&ref={booking.booking_ref}",
                        },
                    },
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#f44336",
                        "action": {
                            "type": "postback",
                            "label": "ปฏิเสธ",
                            "data": f"action=reject_booking&ref={booking.booking_ref}",
                        },
                    },
                ],
            }

        return contents

    def _info_row(self, label: str, value: str) -> dict:
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#888888", "flex": 2},
                {"type": "text", "text": value, "size": "sm", "weight": "bold", "flex": 3, "wrap": True},
            ],
        }

    async def notify_admin_new_booking(self, booking: Booking):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AdminUser).where(AdminUser.is_active == True)
            )
            admins = result.scalars().all()

        bubble = self._build_booking_bubble(booking, include_admin_buttons=True)
        flex = FlexMessage(alt_text=f"จองใหม่ {booking.booking_ref}", contents=FlexContainer.from_dict(bubble))

        for admin in admins:
            if admin.line_id:
                await self.messaging_api.push_message(
                    PushMessageRequest(to=admin.line_id, messages=[flex])
                )

    async def push_booking_confirmed(self, booking: Booking):
        text = (
            f"✅ การจองของคุณได้รับการยืนยันแล้ว!\n\n"
            f"รหัสการจอง: {booking.booking_ref}\n"
            f"เช็คอิน: {booking.check_in}\n"
            f"เช็คเอาต์: {booking.check_out}\n"
            f"ยอดรวม: ฿{booking.total_price:,.0f}"
        )
        await self.push_text(booking.customer_line_id, text)

    async def push_checkin_reminder(self, booking: Booking):
        text = (
            f"⏰ แจ้งเตือน: เช็คอินพรุ่งนี้!\n\n"
            f"รหัส: {booking.booking_ref}\n"
            f"วันที่เช็คอิน: {booking.check_in}\n"
            f"ห้อง: กรุณาแสดง QR Code นี้ที่เคาน์เตอร์\n\n"
            f"ขอบคุณที่ใช้บริการ 🏨"
        )
        await self.push_text(booking.customer_line_id, text)

    async def push_review_request(self, booking: Booking):
        text = (
            f"🙏 ขอบคุณที่ใช้บริการ!\n\n"
            f"รหัสการจอง: {booking.booking_ref}\n\n"
            f"รบกวนรีวิวการเข้าพักด้วยนะคะ ความคิดเห็นของคุณมีความสำคัญมากสำหรับเรา ❤️"
        )
        await self.push_text(booking.customer_line_id, text)

    async def push_payment_rejected(self, booking: Booking, reason: str):
        text = (
            f"❌ สลิปการชำระเงินถูกปฏิเสธ\n\n"
            f"รหัสการจอง: {booking.booking_ref}\n"
            f"เหตุผล: {reason}\n\n"
            f"กรุณาอัปโหลดสลิปใหม่ที่ถูกต้อง หรือติดต่อเจ้าหน้าที่เพื่อขอความช่วยเหลือ"
        )
        await self.push_text(booking.customer_line_id, text)

    async def reply_checkin_list(self, reply_token: str, bookings: list):
        if not bookings:
            await self.reply_text(reply_token, "ไม่มีรายการเช็คอินวันนี้")
            return

        lines = ["📋 รายการเช็คอินวันนี้\n"]
        for i, b in enumerate(bookings, 1):
            lines.append(f"{i}. {b.booking_ref} - {b.customer_name} ({b.customer_phone})")

        await self.reply_text(reply_token, "\n".join(lines))

    async def notify_super_admin_date_blocked(
        self,
        date_str: str,
        reason: str,
        blocked_by_name: str,
    ):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AdminUser).where(
                    AdminUser.is_active == True,
                    AdminUser.role == "super_admin",
                    AdminUser.line_id.isnot(None),
                )
            )
            super_admins = result.scalars().all()

        text = (
            f"🔒 แจ้งเตือน: ปิดวันที่\n\n"
            f"วันที่: {date_str}\n"
            f"เหตุผล: {reason or 'ไม่ระบุ'}\n"
            f"โดย: {blocked_by_name}"
        )
        for sa in super_admins:
            await self.push_text(sa.line_id, text)

    async def push_daily_summary(self, admin_line_id: str, stats: dict):
        text = (
            f"📊 สรุปประจำวัน {stats.get('date', '')}\n\n"
            f"💰 รายได้วันนี้: ฿{stats.get('revenue', 0):,.0f}\n"
            f"📅 จองใหม่: {stats.get('new_bookings', 0)} ห้อง\n"
            f"🏠 เช็คอิน: {stats.get('checkins', 0)} ห้อง\n"
            f"👋 เช็คเอาต์: {stats.get('checkouts', 0)} ห้อง\n"
            f"🛏 ห้องว่าง: {stats.get('available_rooms', 0)} ห้อง"
        )
        await self.push_text(admin_line_id, text)

    async def reply_room_carousel(self, reply_token: str, rooms: list):
        if not rooms:
            await self.reply_text(reply_token, "ขณะนี้ไม่มีห้องว่าง กรุณาติดต่อเจ้าหน้าที่")
            return
        carousel = self.build_room_carousel(rooms)
        flex = FlexMessage(
            alt_text="ห้องพักที่ว่างอยู่",
            contents=FlexContainer.from_dict(carousel),
        )
        await self.messaging_api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[flex])
        )

    def build_room_carousel(self, rooms: list) -> dict:
        bubbles = []
        for room in rooms[:10]:  # LINE carousel max 12
            _raw_url = next(
                (img.url for img in room.images if img.is_cover),
                next((img.url for img in room.images), None),
            )
            if _raw_url and _raw_url.startswith("/"):
                cover_url = f"{settings.APP_URL}{_raw_url}"
            elif _raw_url:
                cover_url = _raw_url
            else:
                cover_url = "https://placehold.co/1200x800/e2e8f0/94a3b8?text=No+Image"
            bubble = {
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": cover_url,
                    "size": "full",
                    "aspectRatio": "3:2",
                    "aspectMode": "cover",
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": room.name, "weight": "bold", "size": "xl"},
                        {"type": "text", "text": room.type.title(), "size": "sm", "color": "#888888"},
                        {
                            "type": "text",
                            "text": f"฿{room.price_per_night:,.0f}/คืน",
                            "size": "lg",
                            "color": "#1a73e8",
                            "weight": "bold",
                        },
                    ],
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "action": {
                                "type": "uri",
                                "label": "จองเลย",
                                "uri": f"https://liff.line.me/{settings.LIFF_ID}?room_id={room.id}",
                            },
                        }
                    ],
                },
            }
            bubbles.append(bubble)

        return {"type": "carousel", "contents": bubbles}

    _TYPE_LABELS = {
        "standard": "Standard", "deluxe": "Deluxe",
        "suite": "Suite", "family": "Family", "superior": "Superior",
    }

    def _cover_url(self, room) -> str:
        raw = next((img.url for img in room.images if img.is_cover),
                   next((img.url for img in room.images), None))
        if raw and raw.startswith("/"):
            return f"{settings.APP_URL}{raw}"
        return raw or "https://placehold.co/1200x800/e2e8f0/94a3b8?text=No+Image"

    def build_room_type_carousel(self, rooms: list) -> dict:
        from collections import defaultdict
        groups: dict[str, list] = defaultdict(list)
        for r in rooms:
            groups[r.type].append(r)

        bubbles = []
        for room_type, type_rooms in groups.items():
            first = type_rooms[0]
            label = self._TYPE_LABELS.get(room_type, room_type.title())
            min_price = min(r.price_per_night for r in type_rooms)
            desc = (first.description or "")[:80]
            available = len(type_rooms)
            body_contents = [
                {"type": "text", "text": f"ห้อง{label}", "weight": "bold", "size": "xl"},
                {"type": "text", "text": f"ว่าง {available} ห้อง", "size": "sm", "color": "#0f9d58", "margin": "xs"},
                {"type": "text", "text": f"เริ่มต้น ฿{min_price:,.0f}/คืน",
                 "size": "lg", "color": "#1a73e8", "weight": "bold", "margin": "sm"},
            ]
            if desc:
                body_contents.append(
                    {"type": "text", "text": desc, "size": "sm", "color": "#666666", "wrap": True, "margin": "sm"}
                )
            bubbles.append({
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": self._cover_url(first),
                    "size": "full",
                    "aspectRatio": "3:2",
                    "aspectMode": "cover",
                },
                "body": {"type": "box", "layout": "vertical", "contents": body_contents},
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [{
                        "type": "button",
                        "style": "primary",
                        "action": {
                            "type": "uri",
                            "label": "จองห้องประเภทนี้",
                            "uri": f"https://liff.line.me/{settings.LIFF_ID}?room_type={room_type}",
                        },
                    }],
                },
            })
        return {"type": "carousel", "contents": bubbles}

    async def reply_room_type_carousel(self, reply_token: str, rooms: list):
        if not rooms:
            await self.reply_text(reply_token, "ขณะนี้ไม่มีห้องว่าง กรุณาติดต่อเจ้าหน้าที่")
            return
        flex = FlexMessage(
            alt_text="ห้องพักตามประเภท",
            contents=FlexContainer.from_dict(self.build_room_type_carousel(rooms)),
        )
        await self.messaging_api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[flex])
        )
