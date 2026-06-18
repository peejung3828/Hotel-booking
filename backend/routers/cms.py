from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from jose import JWTError, jwt

from backend.config import settings
from backend.database import get_db
from backend.models.room import Room
from backend.models.booking import Booking
from backend.models.payment import Payment
from backend.models.coupon import Coupon
from backend.models.user import AdminUser
from backend.models.line_config import BlockedDate

router = APIRouter()
templates = Jinja2Templates(directory="backend/templates")


def get_token_from_request(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return token


async def cms_auth(request: Request, db: AsyncSession = Depends(get_db)) -> AdminUser:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=307, headers={"Location": "/cms/login"})
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=307, headers={"Location": "/cms/login"})

    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=307, headers={"Location": "/cms/login"})
    return user


async def cms_super_admin(user: AdminUser = Depends(cms_auth)) -> AdminUser:
    if user.role != "super_admin":
        raise HTTPException(status_code=307, headers={"Location": "/cms/dashboard"})
    return user


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_auth),
):
    today = date.today()

    revenue_result = await db.execute(
        select(func.sum(Payment.amount)).where(
            and_(
                func.date(Payment.created_at) == today,
                Payment.status == "verified",
            )
        )
    )
    revenue_today = revenue_result.scalar() or 0

    bookings_today = await db.execute(
        select(func.count(Booking.id)).where(func.date(Booking.created_at) == today)
    )
    checkins_today = await db.execute(
        select(func.count(Booking.id)).where(
            and_(Booking.check_in == today, Booking.status == "confirmed")
        )
    )
    available_rooms = await db.execute(
        select(func.count(Room.id)).where(
            and_(Room.status == "available", Room.is_active == True)
        )
    )

    recent_bookings_result = await db.execute(
        select(Booking).order_by(Booking.created_at.desc()).limit(10)
    )
    recent_bookings = recent_bookings_result.scalars().all()

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "revenue_today": revenue_today,
        "bookings_today": bookings_today.scalar() or 0,
        "checkins_today": checkins_today.scalar() or 0,
        "available_rooms": available_rooms.scalar() or 0,
        "recent_bookings": recent_bookings,
    })


@router.get("/rooms", response_class=HTMLResponse)
async def rooms_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_super_admin),
):
    result = await db.execute(
        select(Room).options(selectinload(Room.images)).order_by(Room.created_at.desc())
    )
    rooms = result.scalars().all()
    return templates.TemplateResponse(request, "rooms/list.html", {
        "user": user, "rooms": rooms
    })


@router.get("/rooms/create", response_class=HTMLResponse)
async def room_create_page(
    request: Request,
    user: AdminUser = Depends(cms_super_admin),
):
    return templates.TemplateResponse(request, "rooms/form.html", {
        "user": user, "room": None
    })


@router.get("/rooms/{room_id}/edit", response_class=HTMLResponse)
async def room_edit_page(
    room_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_super_admin),
):
    result = await db.execute(
        select(Room).options(selectinload(Room.images)).where(Room.id == room_id)
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return templates.TemplateResponse(request, "rooms/form.html", {
        "user": user, "room": room
    })


@router.get("/rooms/{room_id}/images", response_class=HTMLResponse)
async def room_images_page(
    room_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_super_admin),
):
    result = await db.execute(
        select(Room).options(selectinload(Room.images)).where(Room.id == room_id)
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return templates.TemplateResponse(request, "rooms/images.html", {
        "user": user, "room": room
    })


@router.get("/bookings", response_class=HTMLResponse)
async def bookings_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_auth),
    status: str | None = None,
    q: str | None = None,
):
    from sqlalchemy import or_
    stmt = select(Booking).options(selectinload(Booking.room)).order_by(Booking.created_at.desc())
    if status:
        stmt = stmt.where(Booking.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Booking.booking_ref.ilike(like),
                Booking.customer_name.ilike(like),
                Booking.customer_phone.ilike(like),
            )
        )
    result = await db.execute(stmt.limit(200))
    bookings = result.scalars().all()

    return templates.TemplateResponse(request, "bookings/list.html", {
        "user": user,
        "bookings": bookings,
        "status_filter": status or "",
        "q": q or "",
    })


@router.get("/bookings/create", response_class=HTMLResponse)
async def booking_create_page(
    request: Request,
    user: AdminUser = Depends(cms_auth),
):
    return templates.TemplateResponse(request, "bookings/create.html", {
        "user": user,
    })


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_auth),
):
    today = date.today()
    start_of_month = today.replace(day=1)
    end_of_month = (start_of_month + timedelta(days=32)).replace(day=1)

    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.check_in >= start_of_month,
                Booking.check_in < end_of_month,
                Booking.status.in_(["pending", "confirmed", "checked_in"]),
            )
        ).order_by(Booking.check_in)
    )
    bookings = result.scalars().all()

    rooms_result = await db.execute(select(Room).where(Room.is_active == True))
    rooms = rooms_result.scalars().all()

    blocked_result = await db.execute(select(BlockedDate).order_by(BlockedDate.date))
    blocked_dates = [
        {"id": str(b.id), "date": str(b.date), "reason": b.reason or ""}
        for b in blocked_result.scalars().all()
    ]

    bookings_json = [
        {
            "booking_ref": b.booking_ref,
            "check_in": str(b.check_in),
            "check_out": str(b.check_out),
            "nights": b.nights,
            "customer_name": b.customer_name,
            "total_price": float(b.total_price),
            "status": b.status,
        }
        for b in bookings
    ]

    return templates.TemplateResponse(request, "bookings/calendar.html", {
        "user": user,
        "bookings": bookings_json,
        "rooms": rooms,
        "today": today,
        "start_of_month": start_of_month,
        "blocked_dates": blocked_dates,
    })


@router.get("/coupons", response_class=HTMLResponse)
async def coupons_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_super_admin),
):
    result = await db.execute(select(Coupon).order_by(Coupon.created_at.desc()))
    coupons = result.scalars().all()
    return templates.TemplateResponse(request, "coupons/list.html", {
        "user": user, "coupons": coupons, "today": date.today()
    })


@router.get("/rich-menu", response_class=HTMLResponse)
async def rich_menu_page(
    request: Request,
    user: AdminUser = Depends(cms_super_admin),
):
    liff_url = f"https://liff.line.me/{settings.LIFF_ID}" if settings.LIFF_ID else ""
    return templates.TemplateResponse(request, "rich_menu/editor.html", {
        "user": user,
        "liff_url": liff_url,
    })


@router.get("/payments", response_class=HTMLResponse)
async def payments_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_auth),
):
    result = await db.execute(
        select(Payment)
        .options(selectinload(Payment.booking))
        .order_by(Payment.created_at.desc())
        .limit(200)
    )
    raw = result.scalars().all()

    payments = [
        {
            "payment": p,
            "booking_ref": p.booking.booking_ref if p.booking else "—",
            "customer_name": p.booking.customer_name if p.booking else "—",
            "customer_phone": p.booking.customer_phone if p.booking else "—",
        }
        for p in raw
    ]

    return templates.TemplateResponse(request, "payments/list.html", {
        "user": user, "payments": payments,
    })


@router.get("/admin-users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_super_admin),
):
    result = await db.execute(select(AdminUser).order_by(AdminUser.created_at.desc()))
    users = result.scalars().all()
    return templates.TemplateResponse(request, "admin_users/list.html", {
        "user": user,
        "users": users,
        "current_user_id": str(user.id),
    })


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(
    request: Request,
    user: AdminUser = Depends(cms_super_admin),
):
    return templates.TemplateResponse(request, "notifications.html", {
        "user": user,
    })


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    user: AdminUser = Depends(cms_super_admin),
):
    return templates.TemplateResponse(request, "reports/index.html", {"user": user})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(cms_super_admin),
):
    blocked = await db.execute(select(BlockedDate).order_by(BlockedDate.date))
    blocked_dates = blocked.scalars().all()

    def mask(val: str) -> str:
        if not val or len(val) < 8:
            return val or "—"
        return val[:6] + "•" * (len(val) - 10) + val[-4:]

    line_config = {
        "channel_secret": mask(settings.LINE_CHANNEL_SECRET),
        "access_token": mask(settings.LINE_CHANNEL_ACCESS_TOKEN),
        "liff_id": settings.LIFF_ID or "—",
    }

    return templates.TemplateResponse(request, "settings.html", {
        "user": user,
        "blocked_dates": blocked_dates,
        "line_config": line_config,
        "app_url": settings.APP_URL,
    })
