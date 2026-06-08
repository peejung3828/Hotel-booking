import io
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

from linebot.v3.messaging import (
    AsyncApiClient, AsyncMessagingApi, AsyncMessagingApiBlob, Configuration,
)
from linebot.v3.messaging.models import (
    RichMenuRequest, RichMenuArea, RichMenuBounds, RichMenuSize,
    URIAction, MessageAction, PostbackAction,
)

from backend.config import settings
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

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), "#f8f9fa")
    draw = ImageDraw.Draw(img)

    try:
        font_label = ImageFont.truetype("arial.ttf", 72)
        font_icon = ImageFont.truetype("seguiemj.ttf", 120)
    except Exception:
        font_label = ImageFont.load_default()
        font_icon = font_label

    for i, btn in enumerate(buttons):
        col = i % cols
        row = i // cols
        x0 = col * cell_w
        y0 = row * cell_h
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        # Background
        color = BUTTON_COLORS[i % len(BUTTON_COLORS)]
        draw.rectangle([x0 + 4, y0 + 4, x1 - 4, y1 - 4], fill=color, outline="#ffffff", width=3)

        # Label text centered
        label = btn.label
        cx = x0 + cell_w // 2
        cy = y0 + cell_h // 2

        # Try to draw icon above label
        try:
            bbox_icon = draw.textbbox((cx, cy - 80), btn.icon, font=font_icon, anchor="mm")
            draw.text((cx, cy - 80), btn.icon, font=font_icon, fill="#ffffff", anchor="mm")
            draw.text((cx, cy + 80), label, font=font_label, fill="#ffffff", anchor="mm")
        except Exception:
            draw.text((cx, cy), label, font=font_label, fill="#ffffff", anchor="mm")

        # Border between cells
        if col < cols - 1:
            draw.line([x1, y0, x1, y1], fill="#ffffff", width=4)
        if row < rows - 1:
            draw.line([x0, y1, x1, y1], fill="#ffffff", width=4)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@router.post("/deploy")
async def deploy_rich_menu(
    body: DeployRequest,
    _=Depends(require_admin),
):
    if not settings.LINE_CHANNEL_ACCESS_TOKEN or settings.LINE_CHANNEL_ACCESS_TOKEN == "your_line_channel_access_token":
        raise HTTPException(status_code=400, detail="LINE_CHANNEL_ACCESS_TOKEN not configured")

    if not body.buttons:
        raise HTTPException(status_code=422, detail="At least one button required")

    buttons = body.buttons[:6]
    configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)

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
                chat_bar_text="เมนู",
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

            # 3. Set as default
            await messaging_api.set_default_rich_menu(rich_menu_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LINE API error: {str(e)}")

    return {"rich_menu_id": rich_menu_id, "name": name, "buttons": n}
