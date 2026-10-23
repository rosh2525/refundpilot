import asyncio
import json
import time
from decimal import Decimal
import httpx
from .config import settings

BASE = "https://api-m.sandbox.paypal.com"

class PayPalError(Exception):
    def __init__(self, message, uncertain=False, code=None):
        super().__init__(message)
        self.uncertain = uncertain
        self.code = code

class PayPal:
    def __init__(self):
        self.token = None
        self.expires_at = 0
        self.lock = asyncio.Lock()

    async def access_token(self):
        async with self.lock:
            if self.token and self.expires_at > time.time() + 60:
                return self.token
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.post(BASE + "/v1/oauth2/token", auth=(settings.paypal_client_id, settings.paypal_client_secret), data={"grant_type": "client_credentials"})
            if response.status_code != 200:
                raise PayPalError("PayPal authentication failed. Check the sandbox app credentials.")
            value = response.json()
            self.token = value["access_token"]
            self.expires_at = time.time() + value.get("expires_in", 300)
            return self.token

    async def call(self, method, path, payload=None, request_id=None):
        try:
            token = await self.access_token()
            headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "Prefer": "return=representation"}
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
                response = await client.request(method, BASE + path, headers=headers, **({"content": payload} if isinstance(payload, bytes) else {"json": payload}))
            if response.status_code >= 400:
                if response.status_code == 401:
                    self.token = None
                try:
                    data = response.json()
                    code = data.get("details", [{}])[0].get("issue") or data.get("name", "PAYPAL_ERROR")
                except (ValueError, IndexError, AttributeError):
                    code = "PAYPAL_ERROR"
                raise PayPalError("PayPal returned " + str(code), uncertain=method == "POST" and (response.status_code >= 500 or response.status_code in {409, 429}), code=code)
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            raise PayPalError("PayPal could not confirm the request. Reconciliation is required.", uncertain=method == "POST") from exc

    async def create_order(self, request_id):
        return await self.call("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{"reference_id": "northstar-demo", "description": "Northstar desk essentials — sandbox demo", "amount": {"currency_code": "USD", "value": "20.00"}}],
            "payment_source": {"paypal": {"experience_context": {"return_url": settings.app_url + "/?checkout=approved", "cancel_url": settings.app_url + "/?checkout=cancelled", "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"}}},
        }, request_id)

    async def capture(self, order_id, request_id):
        return await self.call("POST", f"/v2/checkout/orders/{order_id}/capture", {}, request_id)

    async def get_capture(self, capture_id):
        return await self.call("GET", f"/v2/payments/captures/{capture_id}")

    async def refund(self, capture_id, payload, request_id):
        return await self.call("POST", f"/v2/payments/captures/{capture_id}/refund", payload, request_id)

    async def get_refund(self, refund_id):
        return await self.call("GET", f"/v2/payments/refunds/{refund_id}")

    async def verify(self, headers, event, raw=None):
        required = ["paypal-transmission-id", "paypal-transmission-time", "paypal-cert-url", "paypal-transmission-sig", "paypal-auth-algo"]
        if any(not headers.get(key) for key in required):
            return False
        from urllib.parse import urlsplit
        cert = urlsplit(headers["paypal-cert-url"])
        if cert.scheme != "https" or cert.hostname not in {"api.paypal.com", "api.sandbox.paypal.com", "api-m.paypal.com", "api-m.sandbox.paypal.com"}:
            return False
        envelope = {
            "transmission_id": headers["paypal-transmission-id"], "transmission_time": headers["paypal-transmission-time"],
            "cert_url": headers["paypal-cert-url"], "transmission_sig": headers["paypal-transmission-sig"],
            "auth_algo": headers["paypal-auth-algo"], "webhook_id": settings.paypal_webhook_id, "webhook_event": event,
        }
        if raw is not None:
            # Preserve the exact received event representation inside the verification envelope.
            envelope.pop("webhook_event")
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                return False
            body = json.dumps(envelope, separators=(",", ":")).encode()[:-1] + b',"webhook_event":' + raw + b'}'
        else:
            body = envelope
        value = await self.call("POST", "/v1/notifications/verify-webhook-signature", body)
        return value.get("verification_status") == "SUCCESS"

paypal = PayPal()

def cents(amount):
    value = Decimal(str(amount["value"])) * 100
    if value != value.to_integral_value() or amount.get("currency_code") != "USD":
        raise PayPalError("Unexpected payment amount or currency; manual review required.")
    return int(value)
