from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from backend.config import settings
from backend.database import engine, Base
from backend.routers import (
    webhook, rooms, bookings, payments, coupons, cms, auth, upload,
)
from backend.routers import admin_users, notifications, blocked_dates, liff_pages, line_rich_menu, reports
from backend.services.notification_service import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — schema managed by Alembic, not create_all
    app.state.redis = await aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )

    scheduler.start()

    yield

    # Shutdown
    scheduler.shutdown()
    await app.state.redis.close()
    await engine.dispose()


app = FastAPI(
    title="Hotel Room Booking System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="backend/static"), name="static")

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(rooms.router, prefix="/api/rooms", tags=["rooms"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["bookings"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(coupons.router, prefix="/api/coupons", tags=["coupons"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(admin_users.router, prefix="/api/admin-users", tags=["admin-users"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(blocked_dates.router, prefix="/api/blocked-dates", tags=["blocked-dates"])
app.include_router(webhook.router, tags=["webhook"])
app.include_router(liff_pages.router, prefix="/liff", tags=["liff"])
app.include_router(line_rich_menu.router, prefix="/api/line/rich-menu", tags=["rich-menu"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(cms.router, prefix="/cms", tags=["cms"])


@app.get("/health")
async def health():
    return {"status": "ok"}
