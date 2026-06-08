import hashlib
import hmac
import base64
import uuid
import json
from datetime import datetime

import httpx

from backend.config import settings

SANDBOX_URL = "https://sandbox-api-pay.line.me"
PRODUCTION_URL = "https://api-pay.line.me"


class LinePayService:
    def __init__(self):
        self.channel_id = settings.LINE_PAY_CHANNEL_ID
        self.channel_secret = settings.LINE_PAY_CHANNEL_SECRET
        self.base_url = SANDBOX_URL if settings.LINE_PAY_SANDBOX else PRODUCTION_URL

    def _is_configured(self) -> bool:
        return bool(self.channel_id and self.channel_secret
                    and self.channel_id != "your_line_pay_channel_id")

    def _sign(self, uri: str, body: str, nonce: str) -> str:
        text = self.channel_secret + uri + body + nonce
        sig = hmac.new(
            self.channel_secret.encode("utf-8"),
            text.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(sig).decode("utf-8")

    def _headers(self, uri: str, body: str = "") -> dict:
        nonce = str(uuid.uuid4())
        return {
            "Content-Type": "application/json",
            "X-LINE-ChannelId": self.channel_id,
            "X-LINE-Authorization-Nonce": nonce,
            "X-LINE-Authorization": self._sign(uri, body, nonce),
        }

    async def request_payment(
        self,
        booking_ref: str,
        amount: float,
        room_name: str,
    ) -> dict:
        """
        Create a LINE Pay payment request.
        Returns {"payment_url": str, "transaction_id": str}
        """
        if not self._is_configured():
            raise ValueError("LINE Pay is not configured")

        amount_int = int(amount)
        confirm_url = f"{settings.APP_URL}/api/payments/linepay/confirm"
        cancel_url = f"{settings.APP_URL}/api/payments/linepay/cancel"

        payload = {
            "amount": amount_int,
            "currency": "THB",
            "orderId": booking_ref,
            "packages": [
                {
                    "id": f"pkg-{booking_ref}",
                    "amount": amount_int,
                    "name": "Hotel Room Booking",
                    "products": [
                        {
                            "name": f"{room_name} — {booking_ref}",
                            "quantity": 1,
                            "price": amount_int,
                        }
                    ],
                }
            ],
            "redirectUrls": {
                "confirmUrl": confirm_url,
                "cancelUrl": cancel_url,
            },
        }

        uri = "/v3/payments/request"
        body_str = json.dumps(payload, separators=(",", ":"))
        headers = self._headers(uri, body_str)

        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            res = await client.post(uri, content=body_str, headers=headers)
            res.raise_for_status()
            data = res.json()

        if data.get("returnCode") != "0000":
            raise ValueError(f"LINE Pay error: {data.get('returnMessage')}")

        info = data["info"]
        return {
            "payment_url": info["paymentUrl"]["web"],
            "payment_url_app": info["paymentUrl"].get("app", ""),
            "transaction_id": str(info["transactionId"]),
        }

    async def confirm_payment(self, transaction_id: str, amount: float) -> dict:
        """
        Confirm a LINE Pay transaction after redirect.
        Returns {"status": "success"|"failed", "transaction_id": str}
        """
        if not self._is_configured():
            raise ValueError("LINE Pay is not configured")

        uri = f"/v3/payments/{transaction_id}/confirm"
        payload = {"amount": int(amount), "currency": "THB"}
        body_str = json.dumps(payload, separators=(",", ":"))
        headers = self._headers(uri, body_str)

        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            res = await client.post(uri, content=body_str, headers=headers)
            res.raise_for_status()
            data = res.json()

        success = data.get("returnCode") == "0000"
        return {
            "status": "success" if success else "failed",
            "transaction_id": transaction_id,
            "return_code": data.get("returnCode"),
            "return_message": data.get("returnMessage"),
        }

    async def check_payment_status(self, order_id: str) -> dict:
        """Check payment status by orderId (booking_ref)."""
        if not self._is_configured():
            raise ValueError("LINE Pay is not configured")

        uri = f"/v3/payments/requests/{order_id}/check"
        qs = ""
        headers = self._headers(uri, qs)

        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            res = await client.get(uri, headers=headers)
            res.raise_for_status()
            return res.json()
