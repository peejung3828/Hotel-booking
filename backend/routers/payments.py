import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.config import settings
from backend.services.image_service import ImageService
from backend.services.line_pay_service import LinePayService

from backend.database import get_db
from backend.models.payment import Payment
from backend.models.booking import Booking
from backend.schemas.payment import PaymentCreate, PaymentOut, PaymentVerify, PaymentReject
from backend.services.payment_service import PaymentService
from backend.routers.auth import require_admin, get_current_user
from backend.models.user import AdminUser

router = APIRouter()


@router.post("", response_model=PaymentOut)
async def create_payment(data: PaymentCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Booking).where(Booking.id == data.booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot pay for cancelled booking")

    service = PaymentService()

    if data.method in ("debit_card", "credit_card") and data.omise_token:
        charge_id = await service.charge_omise(data.omise_token, data.amount)
        payment = Payment(
            booking_id=data.booking_id,
            method=data.method,
            amount=data.amount,
            status="verified",
            omise_charge_id=charge_id,
            verified_at=datetime.utcnow(),
            verified_by="omise_auto",
        )
    else:
        payment = Payment(
            booking_id=data.booking_id,
            method=data.method,
            amount=data.amount,
            status="pending",
        )

    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


@router.post("/slip", response_model=PaymentOut)
async def attach_slip(
    payment_id: uuid.UUID,
    slip_url: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment.slip_url = slip_url
    await db.commit()
    await db.refresh(payment)
    return payment


@router.post("/upload-slip", response_model=PaymentOut)
async def upload_slip(
    booking_ref: str = Form(...),
    amount: float = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    booking_result = await db.execute(
        select(Booking).where(Booking.booking_ref == booking_ref)
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot pay for cancelled booking")

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=422, detail="Only JPEG, PNG, WebP images allowed")

    contents = await file.read()
    service = ImageService()
    filename = f"{uuid.uuid4()}.jpg"
    upload_dir = Path(settings.UPLOAD_DIR) / "slips"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    await service.resize_and_save_slip(contents, str(file_path))
    slip_url = f"/static/uploads/slips/{filename}"

    payment = Payment(
        booking_id=booking.id,
        method="bank_transfer",
        amount=amount,
        status="pending",
        slip_url=slip_url,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


@router.put("/{payment_id}/verify", response_model=PaymentOut)
async def verify_payment(
    payment_id: uuid.UUID,
    body: PaymentVerify,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment.status = "verified"
    payment.verified_at = datetime.utcnow()
    payment.verified_by = admin.name

    # Auto-confirm booking
    booking_result = await db.execute(select(Booking).where(Booking.id == payment.booking_id))
    booking = booking_result.scalar_one_or_none()
    if booking and booking.status == "pending":
        booking.status = "confirmed"

    await db.commit()
    await db.refresh(payment)

    if booking and booking.status == "confirmed":
        try:
            from backend.services.line_service import LineService
            await LineService().push_booking_confirmed(booking)
        except Exception:
            pass

    return payment


@router.put("/{payment_id}/reject", response_model=PaymentOut)
async def reject_payment(
    payment_id: uuid.UUID,
    body: PaymentReject,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment.status = "rejected"
    payment.rejection_reason = body.rejection_reason

    booking_result = await db.execute(select(Booking).where(Booking.id == payment.booking_id))
    booking = booking_result.scalar_one_or_none()

    await db.commit()
    await db.refresh(payment)

    if booking:
        try:
            from backend.services.line_service import LineService
            await LineService().push_payment_rejected(booking, body.rejection_reason)
        except Exception:
            pass

    return payment


@router.get("", response_model=list[PaymentOut])
async def list_payments(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Payment).order_by(Payment.created_at.desc()))
    return result.scalars().all()


# ─── PromptPay / QR ──────────────────────────────────────────────────────────

class PromptPayRequest(BaseModel):
    booking_ref: str


@router.post("/promptpay/request")
async def promptpay_request(
    body: PromptPayRequest,
    db: AsyncSession = Depends(get_db),
):
    booking_result = await db.execute(
        select(Booking).where(Booking.booking_ref == body.booking_ref)
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status not in ("pending",):
        raise HTTPException(status_code=400, detail="Booking is not pending payment")

    svc = PaymentService()
    try:
        result = await svc.create_promptpay_charge(
            booking.total_price,
            f"Hotel booking {booking.booking_ref}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PromptPay error: {e}")

    payment = Payment(
        booking_id=booking.id,
        method="qr_promptpay",
        amount=booking.total_price,
        status="pending",
        omise_charge_id=result["charge_id"],
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return {"qr_url": result["qr_url"], "charge_id": result["charge_id"], "amount": result["amount"], "payment_id": str(payment.id)}


@router.get("/promptpay/status/{charge_id}")
async def promptpay_status(charge_id: str, db: AsyncSession = Depends(get_db)):
    """Poll Omise charge status and update payment if paid."""
    svc = PaymentService()
    try:
        charge = await svc.retrieve_charge(charge_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if charge["status"] == "successful":
        result = await db.execute(
            select(Payment).where(Payment.omise_charge_id == charge_id)
        )
        payment = result.scalar_one_or_none()
        if payment and payment.status == "pending":
            payment.status = "verified"
            payment.verified_at = datetime.utcnow()
            payment.verified_by = "omise_promptpay"
            booking_result = await db.execute(
                select(Booking).where(Booking.id == payment.booking_id)
            )
            booking = booking_result.scalar_one_or_none()
            if booking:
                booking.status = "confirmed"
            await db.commit()

    return {"status": charge["status"]}


# ─── LINE Pay ────────────────────────────────────────────────────────────────

class LinePayRequest(BaseModel):
    booking_ref: str


@router.post("/linepay/request")
async def linepay_request(
    body: LinePayRequest,
    db: AsyncSession = Depends(get_db),
):
    booking_result = await db.execute(
        select(Booking).where(Booking.booking_ref == body.booking_ref)
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Booking is cancelled")
    if booking.status in ("confirmed", "checked_in", "checked_out"):
        raise HTTPException(status_code=400, detail="Booking already paid")

    from backend.models.room import Room
    room_result = await db.execute(select(Room).where(Room.id == booking.room_id))
    room = room_result.scalar_one_or_none()
    room_name = room.name if room else "Hotel Room"

    service = LinePayService()
    try:
        result = await service.request_payment(
            booking_ref=booking.booking_ref,
            amount=float(booking.total_price),
            room_name=room_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LINE Pay error: {str(e)}")

    payment = Payment(
        booking_id=booking.id,
        method="line_pay",
        amount=float(booking.total_price),
        status="pending",
        transaction_id=result["transaction_id"],
    )
    db.add(payment)
    await db.commit()

    return {
        "payment_url": result["payment_url"],
        "payment_url_app": result["payment_url_app"],
        "transaction_id": result["transaction_id"],
    }


@router.get("/linepay/confirm")
async def linepay_confirm(
    transactionId: str = Query(...),
    orderId: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    # Find the payment record by booking_ref (orderId) and transaction_id
    booking_result = await db.execute(
        select(Booking).where(Booking.booking_ref == orderId)
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        return RedirectResponse(url=f"/liff/confirm?ref={orderId}&error=booking_not_found")

    payment_result = await db.execute(
        select(Payment).where(
            Payment.booking_id == booking.id,
            Payment.method == "line_pay",
            Payment.transaction_id == transactionId,
            Payment.status == "pending",
        )
    )
    payment = payment_result.scalar_one_or_none()
    if not payment:
        return RedirectResponse(url=f"/liff/confirm?ref={orderId}&error=payment_not_found")

    service = LinePayService()
    try:
        result = await service.confirm_payment(
            transaction_id=transactionId,
            amount=float(booking.total_price),
        )
    except Exception as e:
        return RedirectResponse(url=f"/liff/confirm?ref={orderId}&error=confirm_failed")

    if result["status"] == "success":
        payment.status = "verified"
        payment.verified_at = datetime.utcnow()
        payment.verified_by = "line_pay"
        if booking.status == "pending":
            booking.status = "confirmed"
        await db.commit()

        try:
            from backend.services.line_service import LineService
            line_service = LineService()
            await line_service.push_booking_confirmed(booking)
        except Exception:
            pass

        return RedirectResponse(url=f"/liff/confirm?ref={orderId}")
    else:
        payment.status = "rejected"
        payment.rejection_reason = result.get("return_message", "LINE Pay confirmation failed")
        await db.commit()
        return RedirectResponse(url=f"/liff/confirm?ref={orderId}&error=payment_failed")


@router.get("/linepay/cancel")
async def linepay_cancel(
    orderId: str = Query(...),
):
    return RedirectResponse(url=f"/liff/payment?ref={orderId}&cancelled=1")


# ─── Omise Webhook ───────────────────────────────────────────────────────────

@router.post("/omise-webhook")
async def omise_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Omise charge.complete webhook for PromptPay auto-confirmation."""
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if event.get("key") != "charge.complete":
        return {"received": True}

    charge_data = event.get("data", {})
    charge_id = charge_data.get("id")
    charge_status = charge_data.get("status")

    if not charge_id or charge_status != "successful":
        return {"received": True}

    result = await db.execute(
        select(Payment).where(Payment.omise_charge_id == charge_id, Payment.status == "pending")
    )
    payment = result.scalar_one_or_none()
    if not payment:
        return {"received": True}

    payment.status = "verified"
    payment.verified_at = datetime.utcnow()
    payment.verified_by = "omise_webhook"

    booking_result = await db.execute(select(Booking).where(Booking.id == payment.booking_id))
    booking = booking_result.scalar_one_or_none()
    if booking and booking.status == "pending":
        booking.status = "confirmed"

    await db.commit()

    try:
        from backend.services.line_service import LineService
        line_service = LineService()
        await line_service.push_booking_confirmed(booking)
    except Exception:
        pass

    return {"received": True}
