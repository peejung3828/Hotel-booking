from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from backend.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="backend/templates")

_ctx = {
    "liff_id": settings.LIFF_ID or "",
    "omise_public_key": settings.OMISE_PUBLIC_KEY or "",
    "app_url": settings.APP_URL,
}


@router.get("/", response_class=HTMLResponse)
async def liff_index(request: Request):
    return templates.TemplateResponse(request, "liff/index.html", _ctx)


@router.get("/confirm", response_class=HTMLResponse)
async def liff_confirm(request: Request):
    return templates.TemplateResponse(request, "liff/confirm.html", _ctx)


@router.get("/payment", response_class=HTMLResponse)
async def liff_payment(request: Request):
    return templates.TemplateResponse(request, "liff/payment.html", _ctx)
