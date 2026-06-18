import io
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from linebot.v3.messaging import (
    AsyncApiClient, AsyncMessagingApi, AsyncMessagingApiBlob, Configuration,
)
from linebot.v3.messaging.models import (
    RichMenuRequest, RichMenuArea, RichMenuBounds, RichMenuSize,
    URIAction, MessageAction, PostbackAction,
)

from backend.config import settings
from backend.database import get_db
from backend.models.user import AdminUser
from backend.routers.auth import require_admin

router = APIRouter()

# LINE Rich Menu canvas: 2500 x 843 (standard half-height)
CANVAS_W = 2500
CANVAS_H = 843

BUTTON_COLORS = [
    "#1a73e8", "#0f9d58", "#f4b400", "#db4437", "#ab47bc", "#00acc1"
]


class ButtonConfig(BaseModel):
    label: str
    icon: str
    action: str   # uri | message | postback
    value: str


class DeployRequest(BaseModel):
    tab: str
    buttons: list[ButtonConfig]


def _build_action(btn: ButtonConfig):
    if btn.action == "uri":
        uri = btn.value if btn.value.startswith("http") else f"{settings.APP_URL}{btn.value}"
        return URIAction(type="uri", label=btn.label[:20], uri=uri)
    if btn.action == "postback":
        return PostbackAction(type="postback", label=btn.label[:20], data=btn.value)
    return MessageAction(type="message", label=btn.label[:20], text=btn.value or btn.label)


def _build_areas(buttons: list[ButtonConfig]) -> list[RichMenuArea]:
    n = len(buttons)
    if n <= 3:
        cols, rows = n, 1
    elif n <= 4:
        cols, rows = 2, 2
    else:
        cols, rows = 3, 2

    cell_w = CANVAS_W // cols
    cell_h = CANVAS_H // rows
    areas = []
    for i, btn in enumerate(buttons):
        col = i % cols
        row = i // cols
        areas.append(RichMenuArea(
            bounds=RichMenuBounds(
                x=col * cell_w,
                y=row * cell_h,
                width=cell_w,
                height=cell_h,
            ),
            action=_build_action(btn),
        ))
    return areas


_FONT_PATHS = [
    # Linux (Noto — Thai + Latin)
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansThai-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Windows fallback (dev)
    "arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
]

_EMOJI_PATHS = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    "seguiemj.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",
]


def _load_font(size: int, emoji: bool = False) -> ImageFont.FreeTypeFont:
    paths = _EMOJI_PATHS if emoji else _FONT_PATHS
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_text_centered(draw, text: str, cx: int, cy: int, font, color: str = "#ffffff"):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((cx - tw // 2, cy - th // 2), text, font=font, fill=color)
    except Exception:
        draw.text((cx - 40, cy - 20), text, font=font, fill=color)


def _generate_image(buttons: list[ButtonConfig]) -> bytes:
    n = len(buttons)
    if n <= 3:
        cols, rows = n, 1
    elif n <= 4:
        cols, rows = 2, 2
    else:
        cols, rows = 3, 2

    cell_w = CANVAS_W // cols
    cell_h = CANVAS_H // rows

    # White background — matches CMS Preview exactly
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "#ffffff")
    draw = ImageDraw.Draw(img)

    font_label = _load_font(96)

    # Color palette matching BUTTON_COLORS
    ICON_COLORS = ["#1a73e8", "#0f9d58", "#f4b400", "#db4437", "#7b1fa2", "#00acc1"]
    ICON_RADIUS = 130  # colored circle radius (px)

    for i, btn in enumerate(buttons):
        col = i % cols
        row = i // cols
        x0 = col * cell_w
        y0 = row * cell_h
        x1 = x0 + cell_w
        y1 = y0 + cell_h
        cx = (x0 + x1) // 2
        cy = (y0 + y1) // 2

        color = ICON_COLORS[i % len(ICON_COLORS)]

        # Colored circle as icon (reliable without emoji fonts)
        icon_cy = cy - 110
        draw.ellipse(
            [cx - ICON_RADIUS, icon_cy - ICON_RADIUS, cx + ICON_RADIUS, icon_cy + ICON_RADIUS],
            fill=color,
        )

        # Thai label below the circle
        _draw_text_centered(draw, btn.label, cx, cy + 80, font_label, color="#555555")

        # Gray dividers (1px in preview → 3px at 2500px scale)
        if col < cols - 1:
            draw.line([x1, y0, x1, y1], fill="#dddddd", width=3)
        if row < rows - 1:
            draw.line([x0, y1, x1, y1], fill="#dddddd", width=3)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@router.post("/deploy")
async def deploy_rich_menu(
    body: DeployRequest,
    _=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not settings.LINE_CHANNEL_ACCESS_TOKEN or settings.LINE_CHANNEL_ACCESS_TOKEN == "your_line_channel_access_token":
        raise HTTPException(status_code=400, detail="LINE_CHANNEL_ACCESS_TOKEN not configured")

    if not body.buttons:
        raise HTTPException(status_code=422, detail="At least one button required")

    is_admin_menu = body.tab in ("admin", "super_admin")

    # For admin/super_admin menus, we need LINE IDs to link to
    admin_line_ids: list[str] = []
    if is_admin_menu:
        result = await db.execute(
            select(AdminUser.line_id).where(
                AdminUser.is_active == True,
                AdminUser.line_id.isnot(None),
                AdminUser.role == body.tab if body.tab == "super_admin" else AdminUser.role.in_(["admin", "super_admin"]),
            )
        )
        admin_line_ids = [row[0] for row in result.all() if row[0]]
        if not admin_line_ids:
            raise HTTPException(
                status_code=422,
                detail="ไม่พบ Admin ที่มี LINE ID — ตั้งค่า LINE ID ใน Admin Users ก่อน",
            )

    buttons = body.buttons[:6]
    configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)

    rich_menu_id: str = ""
    try:
        async with AsyncApiClient(configuration) as api_client:
            messaging_api = AsyncMessagingApi(api_client)
            blob_api = AsyncMessagingApiBlob(api_client)

            # 1. Create rich menu
            n = len(buttons)
            name = f"Hotel {body.tab.title()} Menu ({n} buttons)"
            rich_menu = RichMenuRequest(
                size=RichMenuSize(width=CANVAS_W, height=CANVAS_H),
                selected=True,
                name=name,
                chat_bar_text="เมนู Admin" if is_admin_menu else "เมนู",
                areas=_build_areas(buttons),
            )
            result = await messaging_api.create_rich_menu(rich_menu)
            rich_menu_id = result.rich_menu_id

            # 2. Upload image
            image_bytes = _generate_image(buttons)
            await blob_api.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=image_bytes,
                _headers={"Content-Type": "image/jpeg"},
            )

            if is_admin_menu:
                # 3a. Link to each admin's LINE account individually
                for line_id in admin_line_ids:
                    try:
                        await messaging_api.link_rich_menu_id_to_user(
                            user_id=line_id,
                            rich_menu_id=rich_menu_id,
                        )
                    except Exception:
                        pass  # skip invalid/blocked LINE IDs silently
            else:
                # 3b. Set as default for all users (customer menu)
                await messaging_api.set_default_rich_menu(rich_menu_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LINE API error: {str(e)}")

    return {
        "rich_menu_id": rich_menu_id,
        "name": name,
        "buttons": n,
        "linked_users": len(admin_line_ids) if is_admin_menu else None,
    }
