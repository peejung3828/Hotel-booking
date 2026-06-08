import omise
from backend.config import settings


class PaymentService:
    def __init__(self):
        omise.api_secret = settings.OMISE_SECRET_KEY
        omise.api_public = settings.OMISE_PUBLIC_KEY

    async def charge_omise(self, token: str, amount: float) -> str:
        """Charge card via Omise and return charge ID."""
        amount_satang = int(amount * 100)  # Omise uses smallest currency unit
        charge = omise.Charge.create(
            amount=amount_satang,
            currency="thb",
            card=token,
            description="Hotel Booking Payment",
        )
        if charge.status != "successful":
            raise ValueError(f"Payment failed: {charge.failure_message}")
        return charge.id

    async def create_promptpay_charge(self, amount: float, description: str) -> dict:
        """Create PromptPay charge and return charge ID + QR image URL."""
        amount_satang = int(amount * 100)
        charge = omise.Charge.create(
            amount=amount_satang,
            currency="thb",
            source={"type": "promptpay"},
            description=description,
        )
        qr_url = None
        try:
            qr_url = charge.source.scannable_code.image.download_uri
        except Exception:
            pass
        return {"charge_id": charge.id, "qr_url": qr_url, "amount": amount, "status": charge.status}

    async def retrieve_charge(self, charge_id: str) -> dict:
        charge = omise.Charge.retrieve(charge_id)
        return {"id": charge.id, "status": charge.status, "amount": charge.amount / 100}
