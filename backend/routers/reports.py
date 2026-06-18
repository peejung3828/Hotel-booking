import asyncio
import calendar
import csv
import io
import smtplib
from datetime import date, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.database import get_db
from backend.models.booking import Booking
from backend.models.room import Room
from backend.routers.auth import require_super_admin

router = APIRouter()

THAI_MONTHS = [
    "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]
ACTIVE = ("confirmed", "checked_in", "checked_out")


def _prev_ym(year: int, month: int):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _change_pct(cur: float, prev: float) -> int | None:
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100)


async def _compute_stats(year: int, month: int, db: AsyncSession) -> dict:
    days = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days)

    py, pm = _prev_ym(year, month)
    prev_days = calendar.monthrange(py, pm)[1]
    prev_start = date(py, pm, 1)
    prev_end = date(py, pm, prev_days)

    # ── All bookings this month (with room loaded) ──
    q = await db.execute(
        select(Booking)
        .options(selectinload(Booking.room))
        .where(Booking.check_in >= start, Booking.check_in <= end)
    )
    all_bookings = q.scalars().all()

    active = [b for b in all_bookings if b.status in ACTIVE]
    revenue = sum(float(b.total_price) for b in active)
    nights_sold = sum(b.nights for b in active)
    family_count = sum(1 for b in active if b.children_count > 0)
    family_pct = round(family_count / len(active) * 100) if active else 0
    ticket_size = round(revenue / len(active)) if active else 0

    status_counts = {
        "checked_out": sum(1 for b in all_bookings if b.status == "checked_out"),
        "confirmed_or_in": sum(1 for b in all_bookings if b.status in ("confirmed", "checked_in")),
        "cancelled": sum(1 for b in all_bookings if b.status == "cancelled"),
    }
    total_all = len(all_bookings)
    cancel_rate = round(status_counts["cancelled"] / total_all * 100) if total_all > 0 else 0

    # ── Previous month ──
    prev_rev_q = await db.execute(
        select(func.coalesce(func.sum(Booking.total_price), 0)).where(
            Booking.check_in >= prev_start, Booking.check_in <= prev_end,
            Booking.status.in_(ACTIVE),
        )
    )
    prev_revenue = float(prev_rev_q.scalar())

    prev_cnt_q = await db.execute(
        select(func.count()).where(
            Booking.check_in >= prev_start, Booking.check_in <= prev_end,
            Booking.status.in_(ACTIVE),
        )
    )
    prev_count = int(prev_cnt_q.scalar())

    prev_nights_q = await db.execute(
        select(func.coalesce(func.sum(Booking.nights), 0)).where(
            Booking.check_in >= prev_start, Booking.check_in <= prev_end,
            Booking.status.in_(ACTIVE),
        )
    )
    prev_nights = int(prev_nights_q.scalar())

    # ── Occupancy ──
    rooms_q = await db.execute(select(func.count()).where(Room.is_active == True))
    total_rooms = int(rooms_q.scalar())
    capacity = total_rooms * days
    prev_capacity = total_rooms * prev_days

    occupancy_pct = round(nights_sold / capacity * 100) if capacity > 0 else 0
    prev_occ_pct = round(prev_nights / prev_capacity * 100) if prev_capacity > 0 else 0
    adr = round(revenue / nights_sold) if nights_sold > 0 else 0

    # ── Top rooms ──
    room_counts: dict[str, int] = {}
    for b in active:
        name = b.room.name if b.room else "ไม่ทราบ"
        room_counts[name] = room_counts.get(name, 0) + 1
    top_rooms = [
        {"name": n, "count": c}
        for n, c in sorted(room_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    ]

    # ── Smart insights ──
    rev_change = _change_pct(revenue, prev_revenue)
    insights = []
    if rev_change is not None and rev_change >= 10:
        insights.append(f"รายได้เพิ่มขึ้น {rev_change}% จากเดือนที่แล้ว แนวโน้มดีมาก! รักษาระดับบริการและโปรโมชันไว้")
    elif rev_change is not None and rev_change <= -10:
        insights.append(f"รายได้ลดลง {abs(rev_change)}% จากเดือนที่แล้ว ควรวางแผนกลยุทธ์การตลาดเพิ่มเติม")
    if family_pct >= 35:
        insights.append(
            f"กลุ่มครอบครัวที่มีเด็กครองสัดส่วน {family_pct}% "
            f"แนะนำจัดโปรโมชัน Family หรือโฆษณาห้อง Family Suite ในเดือนหน้า"
        )
    if occupancy_pct < 60:
        insights.append(
            f"อัตราเข้าพัก {occupancy_pct}% ต่ำกว่าเป้า "
            f"พิจารณาโปรโมชัน Early Bird หรือ Flash Sale เพื่อกระตุ้นการจอง"
        )
    if cancel_rate >= 15:
        insights.append(
            f"อัตราการยกเลิก {cancel_rate}% สูงกว่าปกติ ควรตรวจสอบสาเหตุและปรับนโยบายการยกเลิก"
        )
    if top_rooms:
        insights.append(
            f"ห้อง '{top_rooms[0]['name']}' ขายดีที่สุด ({top_rooms[0]['count']} การจอง) "
            f"พิจารณาปรับราคาหรือโปรโมตห้องประเภทนี้เพิ่มเติม"
        )
    if not insights:
        insights.append("ผลประกอบการของเดือนนี้อยู่ในเกณฑ์ปกติ ติดตามแนวโน้มต่อไปในเดือนหน้า")

    return {
        "year": year,
        "month": month,
        "month_name": THAI_MONTHS[month],
        "days_in_month": days,
        "revenue": revenue,
        "revenue_prev": prev_revenue,
        "revenue_change_pct": rev_change,
        "bookings_active": len(active),
        "bookings_prev": prev_count,
        "bookings_change_pct": _change_pct(len(active), prev_count),
        "ticket_size": ticket_size,
        "occupancy_pct": occupancy_pct,
        "occupancy_prev_pct": prev_occ_pct,
        "occupancy_change_pct": occupancy_pct - prev_occ_pct,
        "adr": adr,
        "nights_sold": nights_sold,
        "total_rooms": total_rooms,
        "top_rooms": top_rooms,
        "family_pct": family_pct,
        "family_count": family_count,
        "status_checked_out": status_counts["checked_out"],
        "status_confirmed_or_in": status_counts["confirmed_or_in"],
        "status_cancelled": status_counts["cancelled"],
        "cancellation_rate_pct": cancel_rate,
        "insights": insights,
    }


def _make_csv_bytes(bookings: list) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([
        "booking_ref", "customer_name", "customer_phone",
        "room_name", "check_in", "check_out", "nights",
        "children", "total_price", "status", "coupon_code", "created_at",
    ])
    for b in bookings:
        w.writerow([
            b.booking_ref, b.customer_name, b.customer_phone,
            b.room.name if b.room else "",
            str(b.check_in), str(b.check_out), b.nights,
            b.children_count, float(b.total_price), b.status,
            b.coupon_code or "", str(b.created_at)[:19],
        ])
    return out.getvalue().encode("utf-8-sig")  # utf-8-sig → Excel opens correctly


def _build_email_html(stats: dict) -> str:
    hotel = settings.APP_NAME
    cms_url = settings.APP_URL + "/cms/reports"

    def thb(n: float) -> str:
        return f"฿{n:,.0f}"

    def badge(pct: int | None) -> str:
        if pct is None:
            return '<span style="color:#999;font-size:11px;">—</span>'
        color = "#2e7d32" if pct > 0 else "#c62828" if pct < 0 else "#555"
        arrow = "🔺" if pct > 0 else "🔻" if pct < 0 else "→"
        sign = "+" if pct > 0 else ""
        return f'<span style="color:{color};font-size:12px;">{arrow} {sign}{pct}% จากเดือนที่แล้ว</span>'

    medals = ["🥇", "🥈", "🥉"]
    room_rows = "".join(
        f'<tr><td style="padding:9px 14px;border-bottom:1px solid #f0f0f0;">{medals[i]} {r["name"]}</td>'
        f'<td style="padding:9px 14px;border-bottom:1px solid #f0f0f0;text-align:right;font-weight:bold;">'
        f'{r["count"]} การจอง</td></tr>'
        for i, r in enumerate(stats["top_rooms"])
    ) or '<tr><td colspan="2" style="padding:12px;text-align:center;color:#aaa;">ไม่มีข้อมูล</td></tr>'

    insight_items = "".join(
        f'<p style="margin:5px 0;font-size:13px;line-height:1.7;">📌 {ins}</p>'
        for ins in stats["insights"]
    )

    cancel_icon = "📉" if stats["cancellation_rate_pct"] < 10 else "⚠️"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1);">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#1a73e8 0%,#0d47a1 100%);padding:28px 32px;text-align:center;">
    <div style="font-size:40px;margin-bottom:8px;">🏨</div>
    <h1 style="margin:0;color:#fff;font-size:22px;font-weight:bold;">{hotel}</h1>
    <p style="margin:6px 0 0;color:#c5d8ff;font-size:14px;">
      สรุปผลประกอบการประจำเดือน {stats["month_name"]} {stats["year"]}
    </p>
  </td></tr>

  <!-- Greeting -->
  <tr><td style="padding:22px 32px 4px;">
    <p style="margin:0;color:#444;line-height:1.7;font-size:14px;">
      สวัสดีค่ะ/ครับ คุณผู้บริหาร<br>
      นี่คือสรุปยอดจองและรายได้ของโรงแรมในเดือนที่ผ่านมา
      เพื่อช่วยให้คุณวางแผนกลยุทธ์ได้อย่างแม่นยำยิ่งขึ้นค่ะ
    </p>
  </td></tr>

  <!-- Section 1: Overview -->
  <tr><td style="padding:18px 32px 0;">
    <h2 style="margin:0 0 14px;color:#1a73e8;font-size:15px;border-bottom:2px solid #e8f0fe;padding-bottom:8px;">
      💰 สรุปภาพรวมรายได้ (Overview)
    </h2>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="33%" style="padding:0 6px 0 0;vertical-align:top;">
          <div style="background:#e8f0fe;border-radius:10px;padding:16px 10px;text-align:center;">
            <div style="font-size:20px;font-weight:bold;color:#1a73e8;">{thb(stats["revenue"])}</div>
            <div style="font-size:11px;color:#888;margin-top:4px;">รายได้รวม (verified)</div>
            <div style="margin-top:6px;">{badge(stats["revenue_change_pct"])}</div>
          </div>
        </td>
        <td width="33%" style="padding:0 3px;vertical-align:top;">
          <div style="background:#e8f5e9;border-radius:10px;padding:16px 10px;text-align:center;">
            <div style="font-size:20px;font-weight:bold;color:#2e7d32;">{stats["bookings_active"]}</div>
            <div style="font-size:11px;color:#888;margin-top:4px;">การจองที่สำเร็จ</div>
            <div style="margin-top:6px;">{badge(stats["bookings_change_pct"])}</div>
          </div>
        </td>
        <td width="33%" style="padding:0 0 0 6px;vertical-align:top;">
          <div style="background:#fff8e1;border-radius:10px;padding:16px 10px;text-align:center;">
            <div style="font-size:20px;font-weight:bold;color:#d97706;">{thb(stats["ticket_size"])}</div>
            <div style="font-size:11px;color:#888;margin-top:4px;">ยอดเฉลี่ย/การจอง</div>
            <div style="font-size:11px;color:#aaa;margin-top:4px;">(Ticket Size)</div>
          </div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Section 2: Room Performance -->
  <tr><td style="padding:18px 32px 0;">
    <h2 style="margin:0 0 14px;color:#1a73e8;font-size:15px;border-bottom:2px solid #e8f0fe;padding-bottom:8px;">
      📈 ประสิทธิภาพห้องพัก (Room Performance)
    </h2>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;">
      <tr>
        <td width="48%" style="padding-right:6px;">
          <div style="background:#f3e8ff;border-radius:10px;padding:14px;text-align:center;">
            <div style="font-size:26px;font-weight:bold;color:#7c3aed;">{stats["occupancy_pct"]}%</div>
            <div style="font-size:11px;color:#888;margin-top:4px;">อัตราเข้าพักเฉลี่ย (Occupancy)</div>
            <div style="margin-top:4px;">{badge(stats["occupancy_change_pct"])}</div>
          </div>
        </td>
        <td width="52%" style="padding-left:6px;">
          <div style="background:#fce7f3;border-radius:10px;padding:14px;text-align:center;">
            <div style="font-size:26px;font-weight:bold;color:#be185d;">{thb(stats["adr"])}</div>
            <div style="font-size:11px;color:#888;margin-top:4px;">ราคาเฉลี่ยต่อคืน (ADR)</div>
            <div style="font-size:11px;color:#aaa;margin-top:4px;">{stats["nights_sold"]:,} คืนที่ขายได้</div>
          </div>
        </td>
      </tr>
    </table>
    <p style="margin:0 0 8px;font-size:13px;color:#555;font-weight:bold;">ประเภทห้องพักยอดฮิต 3 อันดับแรก</p>
    <table width="100%" cellpadding="0" cellspacing="0"
      style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
      <tr style="background:#f9fafb;">
        <th style="padding:8px 14px;text-align:left;font-size:12px;color:#9ca3af;font-weight:500;">ห้องพัก</th>
        <th style="padding:8px 14px;text-align:right;font-size:12px;color:#9ca3af;font-weight:500;">จำนวนการจอง</th>
      </tr>
      {room_rows}
    </table>
  </td></tr>

  <!-- Section 3: Customer Insights -->
  <tr><td style="padding:18px 32px 0;">
    <h2 style="margin:0 0 14px;color:#1a73e8;font-size:15px;border-bottom:2px solid #e8f0fe;padding-bottom:8px;">
      👥 พฤติกรรมของลูกค้า (Customer Insights)
    </h2>
    <div style="background:#e0f2fe;border-radius:10px;padding:14px 18px;margin-bottom:12px;">
      <table cellpadding="0" cellspacing="0"><tr>
        <td style="font-size:36px;vertical-align:middle;">👨‍👩‍👧</td>
        <td style="padding-left:14px;vertical-align:middle;">
          <div style="font-size:22px;font-weight:bold;color:#0369a1;">{stats["family_pct"]}%</div>
          <div style="font-size:12px;color:#555;margin-top:2px;">
            สัดส่วนกลุ่มครอบครัวที่มีเด็กมาด้วย ({stats["family_count"]} รายการ)
          </div>
        </td>
      </tr></table>
    </div>
    <p style="margin:0 0 8px;font-size:13px;color:#555;font-weight:bold;">สถานะการจองในระบบ</p>
    <table width="100%" cellpadding="0" cellspacing="0"
      style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
      <tr>
        <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;">
          <span style="background:#dcfce7;color:#166534;padding:2px 10px;border-radius:12px;font-size:12px;">
            ✅ Checked-out สำเร็จ
          </span>
        </td>
        <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;text-align:right;font-weight:bold;font-size:14px;">
          {stats["status_checked_out"]} รายการ
        </td>
      </tr>
      <tr>
        <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;">
          <span style="background:#dbeafe;color:#1d4ed8;padding:2px 10px;border-radius:12px;font-size:12px;">
            🏠 Confirmed / เช็คอิน
          </span>
        </td>
        <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;text-align:right;font-weight:bold;font-size:14px;">
          {stats["status_confirmed_or_in"]} รายการ
        </td>
      </tr>
      <tr>
        <td style="padding:10px 14px;">
          <span style="background:#fee2e2;color:#991b1b;padding:2px 10px;border-radius:12px;font-size:12px;">
            ❌ Cancelled
          </span>
          <span style="color:#aaa;font-size:11px;margin-left:6px;">
            อัตราการยกเลิก {stats["cancellation_rate_pct"]}% {cancel_icon}
          </span>
        </td>
        <td style="padding:10px 14px;text-align:right;font-weight:bold;font-size:14px;">
          {stats["status_cancelled"]} รายการ
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Section 4: Smart Insights -->
  <tr><td style="padding:18px 32px 0;">
    <h2 style="margin:0 0 14px;color:#1a73e8;font-size:15px;border-bottom:2px solid #e8f0fe;padding-bottom:8px;">
      💡 แนะนำสำหรับเดือนหน้า (Smart Insights)
    </h2>
    <div style="background:#fffbeb;border:1px solid #fde68a;border-left:4px solid #f59e0b;
                border-radius:0 8px 8px 0;padding:14px 18px;color:#78350f;">
      {insight_items}
    </div>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f9fafb;padding:22px 32px;text-align:center;border-top:1px solid #e5e7eb;margin-top:18px;">
    <p style="margin:0 0 4px;color:#6b7280;font-size:12px;">
      📎 ไฟล์ข้อมูลรายละเอียด (CSV) แนบมาพร้อมอีเมลนี้ค่ะ
    </p>
    <p style="margin:0 0 16px;color:#9ca3af;font-size:12px;">
      สามารถดูรายงานแบบ interactive ได้ที่ระบบ CMS
    </p>
    <a href="{cms_url}"
      style="display:inline-block;padding:11px 28px;background:#1a73e8;color:#fff;
             text-decoration:none;border-radius:8px;font-weight:bold;font-size:14px;">
      เข้าสู่ระบบจัดการ →
    </a>
    <p style="margin:18px 0 0;color:#d1d5db;font-size:11px;">
      © {stats["year"]} {hotel} · Hotel Management System
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


async def _send_email(stats: dict, csv_bytes: bytes) -> dict:
    if not settings.SMTP_HOST or not settings.REPORT_EMAIL:
        return {"sent": False, "message": "SMTP ยังไม่ได้ตั้งค่า กรุณาเพิ่ม SMTP_HOST และ REPORT_EMAIL ใน .env"}

    html = _build_email_html(stats)
    filename = f"report_{THAI_MONTHS[stats['month']]}_{stats['year']}.csv"

    msg = MIMEMultipart("related")
    msg["Subject"] = (
        f"📊 สรุปผลประกอบการ {settings.APP_NAME} "
        f"ประจำเดือน {stats['month_name']} {stats['year']}"
    )
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = settings.REPORT_EMAIL

    msg.attach(MIMEText(html, "html", "utf-8"))

    attachment = MIMEApplication(csv_bytes, Name=filename)
    attachment["Content-Disposition"] = f'attachment; filename="{filename}"'
    msg.attach(attachment)

    def _send_sync():
        if settings.SMTP_SSL:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            if settings.SMTP_TLS:
                server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()

    await asyncio.to_thread(_send_sync)
    return {"sent": True, "message": "ส่งอีเมลสำเร็จ", "to": settings.REPORT_EMAIL}


# ─── API Endpoints ────────────────────────────────────────────────────────────

@router.get("/monthly")
async def monthly_stats(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin),
):
    now = datetime.now()
    return await _compute_stats(year or now.year, month or now.month, db)


@router.get("/monthly/csv")
async def monthly_csv(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin),
):
    now = datetime.now()
    y = year or now.year
    m = month or now.month

    days = calendar.monthrange(y, m)[1]
    q = await db.execute(
        select(Booking)
        .options(selectinload(Booking.room))
        .where(Booking.check_in >= date(y, m, 1), Booking.check_in <= date(y, m, days))
        .order_by(Booking.check_in)
    )
    bookings = q.scalars().all()
    csv_bytes = _make_csv_bytes(bookings)

    fname = f"report_{THAI_MONTHS[m]}_{y}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.post("/monthly/email")
async def send_monthly_email(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_super_admin),
):
    now = datetime.now()
    y = year or now.year
    m = month or now.month

    stats = await _compute_stats(y, m, db)

    days = calendar.monthrange(y, m)[1]
    q = await db.execute(
        select(Booking)
        .options(selectinload(Booking.room))
        .where(Booking.check_in >= date(y, m, 1), Booking.check_in <= date(y, m, days))
        .order_by(Booking.check_in)
    )
    bookings = q.scalars().all()
    csv_bytes = _make_csv_bytes(bookings)

    try:
        result = await _send_email(stats, csv_bytes)
    except Exception as e:
        result = {"sent": False, "message": str(e)}

    return result
