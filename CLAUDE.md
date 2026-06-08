# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

```bash
# Start all services (PostgreSQL, Redis, migrations, app)
docker compose up -d

# Force-recreate app container after .env changes
docker compose build app && docker compose up -d --force-recreate app

# Rebuild migrate container after adding a new migration file
docker compose build migrate && docker compose up -d --force-recreate

# View logs
docker compose logs app --tail=50
docker compose logs migrate --tail=30

# Run a one-off command inside the app container
docker compose exec app python scripts/seed_admin.py

# Connect to PostgreSQL
docker compose exec db psql -U postgres -d hotel_booking
```

The app runs on `http://localhost:8000`. The CMS is at `/cms`. The LINE webhook is at `/webhook`.

## Adding Alembic Migrations

Migrations live in `alembic/versions/`. Create files manually (not with autogenerate) with sequential short IDs. Always chain `down_revision` to the previous migration ID.

PostgreSQL ENUM changes require dropping the column default first, altering the type, then re-setting the default:
```python
op.execute("ALTER TABLE rooms ALTER COLUMN status DROP DEFAULT")
op.execute("ALTER TABLE rooms ALTER COLUMN status TYPE room_status USING status::room_status")
op.execute("ALTER TABLE rooms ALTER COLUMN status SET DEFAULT 'available'::room_status")
```

## Architecture

### Request Flow

- **API clients** → `/api/*` routers → SQLAlchemy async session via `get_db()` dependency
- **CMS web UI** → `/cms/*` router (cms.py) → Jinja2 templates; auth via `cms_auth()` which reads JWT from cookie or Authorization header
- **LINE users** → `/webhook` → `handle_event()` → `LineService` for replies
- **LIFF pages** → `/liff/*` → Jinja2 templates; customers interact via LINE's in-app browser

### Authentication

Two auth paths, both JWT (HS256, SECRET_KEY):

- **API**: OAuth2 Bearer token (`require_admin` / `require_super_admin` FastAPI dependencies in `backend/routers/auth.py`)
- **CMS**: Token stored in cookie; `cms_auth()` dependency redirects to `/cms/login` if missing/invalid

Roles: `admin`, `super_admin`. LINE webhook uses HMAC-SHA256 signature verification against `LINE_CHANNEL_SECRET`.

### Database

Async SQLAlchemy 2.0 with asyncpg. Always use `selectinload()` when a response schema includes relationship fields — lazy loading raises `MissingGreenlet` in async context. Example:
```python
result = await db.execute(
    select(Room).options(selectinload(Room.images)).where(Room.id == room_id)
)
```

After `db.commit()` in create/update endpoints, do **not** use `db.refresh()` if relationships are needed — re-query with `selectinload` instead.

Redis is used for distributed booking locks (30-second TTL) to prevent double-bookings and for scheduler deduplication.

### Key Services (`backend/services/`)

| Service | Responsibility |
|---|---|
| `BookingService` | Pricing logic (weekday/weekend/holiday), coupon validation, booking-ref generation (`BK-YYYY-XXXX`), Redis locking |
| `PaymentService` | Omise card charges and PromptPay QR (amounts in satang) |
| `LineService` | All LINE Messaging API calls: flex messages, room carousel, push notifications to admins/customers |
| `LinePayService` | LINE Pay API with HMAC-SHA256 nonce auth headers |
| `ImageService` | Async PIL resize to 1200×800 JPEG; slip images use thumbnail without padding |
| `NotificationService` | APScheduler jobs: daily summary (09:00 BKK), check-in reminder (24h prior), payment timeout, checkout review request |

### Image Uploads

Images are saved to `backend/static/uploads/{room_id}/{uuid}.jpg` and served at `/static/uploads/...`. The stored URL is a **relative path**. When sending image URLs to LINE API, always prepend `settings.APP_URL` to make them absolute HTTPS URLs.

### LINE Integration

- **Webhook** (`/webhook`): Handles `follow`, `message`, and `postback` events. Text triggers: `ดูห้อง`, `การจอง`, `เช็คอินวันนี้` (admin only), and booking refs (`BK-*`).
- **Rich Menu**: Managed via `/api/line/rich-menu` and the CMS rich menu editor.
- **LIFF**: Customer booking flow (room selection → date picker → confirmation → payment). LIFF ID comes from `settings.LIFF_ID` (LINE Login channel, not Messaging API channel).

### Router Prefixes

```
/api/auth, /api/rooms, /api/bookings, /api/payments, /api/coupons
/api/upload, /api/admin-users, /api/notifications, /api/blocked-dates
/api/line/rich-menu
/liff          → LIFF app pages (Jinja2)
/cms           → Admin web UI (Jinja2)
/webhook       → LINE webhook (no prefix)
```

## Environment Variables

See `.env.example`. Key vars:
- `APP_URL` — public HTTPS URL (ngrok or production); used to build absolute image URLs for LINE
- `DATABASE_URL` — must use service name `db` (not `localhost`) inside Docker containers
- `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` — from LINE Developers Console (Messaging API channel)
- `LIFF_ID` — from LINE Login channel (not Messaging API channel)
- `OMISE_PUBLIC_KEY` / `OMISE_SECRET_KEY` — Omise dashboard

After changing `.env`, always `--force-recreate` the app container — Docker does not pick up `.env` changes on plain restart.
