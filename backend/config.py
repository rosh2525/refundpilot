import hashlib
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

POLICY = {
    "version": "northstar-2026-01",
    "window_days": 30,
    "clauses": {
        "P1": "Refund requests must be made within 30 days of payment capture.",
        "P2": "A refund must not exceed the requested amount or the remaining refundable payment balance.",
        "P3": "Missing or contradictory information requires merchant review before a refund can be approved.",
        "P4": "Every refund requires explicit merchant approval and returns to the original payment method.",
    },
}
POLICY_HASH = hashlib.sha256(str(POLICY).encode()).hexdigest()

@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./refundpilot.db")
    mode: str = os.getenv("PAYMENT_MODE", "preview")
    app_url: str = (os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000").rstrip("/")
    app_password: str = os.getenv("APP_PASSWORD", "refundpilot-local")
    session_secret: str = os.getenv("SESSION_SECRET", "local-preview-only-change-before-hosting")
    paypal_client_id: str = os.getenv("PAYPAL_CLIENT_ID", "")
    paypal_client_secret: str = os.getenv("PAYPAL_CLIENT_SECRET", "")
    paypal_webhook_id: str = os.getenv("PAYPAL_WEBHOOK_ID", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    worker_enabled: bool = os.getenv("WORKER_ENABLED", "true").lower() == "true"
    ai_daily_limit: int = int(os.getenv("AI_DAILY_LIMIT", "50"))

    def validate(self):
        if self.mode not in {"preview", "sandbox"}:
            raise RuntimeError("PAYMENT_MODE must be preview or sandbox; live payments are unsupported")
        if self.mode == "sandbox":
            if not all((self.paypal_client_id, self.paypal_client_secret, self.paypal_webhook_id)):
                raise RuntimeError("Sandbox mode requires PayPal app credentials and webhook ID")
            if self.app_password == "refundpilot-local" or len(self.app_password) < 12:
                raise RuntimeError("Set a dedicated APP_PASSWORD of at least 12 characters")
            if len(self.session_secret) < 32 or self.session_secret.startswith("local-preview"):
                raise RuntimeError("Set a random SESSION_SECRET of at least 32 characters")
        if self.app_url.startswith("https://") and (self.app_password == "refundpilot-local" or self.session_secret.startswith("local-preview")):
            raise RuntimeError("Hosted deployments require a dedicated password and session secret")

settings = Settings()
