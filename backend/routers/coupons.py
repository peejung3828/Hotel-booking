import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models.coupon import Coupon
from backend.schemas.coupon import CouponCreate, CouponUpdate, CouponOut, CouponValidate, CouponValidateResponse
from backend.routers.auth import require_admin

router = APIRouter()


@router.post("/validate", response_model=CouponValidateResponse)
async def validate_coupon(body: CouponValidate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Coupon).where(Coupon.code == body.code.upper()))
    coupon = result.scalar_one_or_none()

    if not coupon:
        return CouponValidateResponse(valid=False, message="Coupon not found")
    if not coupon.is_active:
        return CouponValidateResponse(valid=False, message="Coupon is inactive")
    if coupon.used_count >= coupon.max_usage:
        return CouponValidateResponse(valid=False, message="Coupon usage limit reached")

    today = date.today()
    if coupon.start_date and today < coupon.start_date:
        return CouponValidateResponse(valid=False, message="Coupon not yet valid")
    if coupon.expire_date and today > coupon.expire_date:
        return CouponValidateResponse(valid=False, message="Coupon has expired")
    if coupon.min_order_amount and body.order_amount < coupon.min_order_amount:
        return CouponValidateResponse(
            valid=False,
            message=f"Minimum order amount is {coupon.min_order_amount:,.0f} THB",
        )

    if coupon.discount_type == "percent":
        discount_amount = body.order_amount * (coupon.discount_value / 100)
    else:
        discount_amount = min(coupon.discount_value, body.order_amount)

    return CouponValidateResponse(
        valid=True,
        discount_type=coupon.discount_type,
        discount_value=coupon.discount_value,
        discount_amount=round(discount_amount, 2),
    )


@router.get("", response_model=list[CouponOut])
async def list_coupons(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Coupon).order_by(Coupon.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=CouponOut)
async def create_coupon(
    data: CouponCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    data.code = data.code.upper()
    existing = await db.execute(select(Coupon).where(Coupon.code == data.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Coupon code already exists")

    coupon = Coupon(**data.model_dump())
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return coupon


@router.put("/{coupon_id}", response_model=CouponOut)
async def update_coupon(
    coupon_id: uuid.UUID,
    data: CouponUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Coupon).where(Coupon.id == coupon_id))
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(coupon, field, value)

    await db.commit()
    await db.refresh(coupon)
    return coupon


@router.delete("/{coupon_id}")
async def delete_coupon(
    coupon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Coupon).where(Coupon.id == coupon_id))
    coupon = result.scalar_one_or_none()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    await db.delete(coupon)
    await db.commit()
    return {"message": "Coupon deleted"}
