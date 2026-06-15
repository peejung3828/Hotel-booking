import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models.line_config import BlockedDate
from backend.models.user import AdminUser
from backend.routers.auth import require_admin, get_current_user

router = APIRouter()


class BlockedDateCreate(BaseModel):
    date: date
    reason: str | None = None


class BlockedDateOut(BaseModel):
    id: uuid.UUID
    date: date
    reason: str | None
    created_at: str

    model_config = {"from_attributes": True}


@router.get("")
async def list_blocked_dates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BlockedDate).order_by(BlockedDate.date))
    return [
        {"id": str(b.id), "date": str(b.date), "reason": b.reason}
        for b in result.scalars().all()
    ]


@router.post("")
async def add_blocked_date(
    data: BlockedDateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
):
    existing = await db.execute(select(BlockedDate).where(BlockedDate.date == data.date))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Date already blocked")

    bd = BlockedDate(date=data.date, reason=data.reason, created_by=current_user.id)
    db.add(bd)
    await db.commit()
    await db.refresh(bd)

    try:
        from backend.services.line_service import LineService
        await LineService().notify_super_admin_date_blocked(
            date_str=str(bd.date),
            reason=bd.reason or "",
            blocked_by_name=current_user.name,
        )
    except Exception:
        pass

    return {"id": str(bd.id), "date": str(bd.date), "reason": bd.reason}


@router.delete("/{bd_id}")
async def remove_blocked_date(
    bd_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
):
    result = await db.execute(select(BlockedDate).where(BlockedDate.id == bd_id))
    bd = result.scalar_one_or_none()
    if not bd:
        raise HTTPException(status_code=404, detail="Blocked date not found")
    await db.delete(bd)
    await db.commit()
    return {"message": "Unblocked"}
