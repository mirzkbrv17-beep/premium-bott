"""To'lov adapterlari. Credential bo'lmasa -> not_configured (soxta muvaffaqiyat yo'q)."""
import hashlib
import hmac
import json
from urllib.parse import urlencode

from ..config import settings
from .base import PaymentEvent, Provider


class MockProvider(Provider):
    """Faqat dev/test: HMAC-SHA256 imzoli webhook bilan to'lovni taqlid qiladi (pul harakatlanmaydi)."""
    code, name = "mock", "Mock (test)"

    def configured(self) -> bool:
        return settings.mock_provider_enabled and not settings.is_prod

    async def create_payment(self, topup, user) -> dict:
        return {"type": "mock", "order_id": topup.public_id, "amount": topup.uzs_amount}

    def verify_webhook(self, headers, body) -> bool:
        sig = headers.get("x-signature", "")
        good = hmac.new(settings.mock_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good)

    def parse_webhook(self, body) -> PaymentEvent:
        d = json.loads(body)
        return PaymentEvent(event_id=str(d["event_id"]), topup_public_id=str(d["order_id"]), status=d["status"],
                            paid_amount=int(d["amount"]), external_id=d.get("external_id"))


class ManualCardProvider(Provider):
    """Karta orqali qo'lda to'lov: rekvizit env'dan; balans faqat admin tasdiqlagach qo'shiladi."""
    code, name, kind = "manual_card", "Karta orqali (qo'lda tasdiq)", "manual"

    def configured(self) -> bool:
        return bool(settings.manual_card_info.strip())

    async def create_payment(self, topup, user) -> dict:
        return {"type": "manual", "instructions": settings.manual_card_info, "amount_uzs": topup.uzs_amount,
                "comment": topup.public_id}


class ClickProvider(Provider):
    """Click Shop API (Prepare/Complete). DIQQAT: haqiqiy merchant hisobsiz sinab ko'rilmagan - README'ga qarang."""
    code, name = "click", "Click"

    def configured(self) -> bool:
        return all([settings.click_service_id, settings.click_merchant_id, settings.click_secret_key])

    async def create_payment(self, topup, user) -> dict:
        q = urlencode({"service_id": settings.click_service_id, "merchant_id": settings.click_merchant_id,
                       "amount": f"{topup.uzs_amount}.00", "transaction_param": topup.public_id,
                       "return_url": settings.webapp_url or ""})
        return {"type": "url", "url": f"https://my.click.uz/services/pay?{q}"}

    @staticmethod
    def sign(p: dict, action: str) -> str:
        parts = [p.get("click_trans_id", ""), p.get("service_id", ""), settings.click_secret_key,
                 p.get("merchant_trans_id", "")]
        if action == "1":
            parts.append(p.get("merchant_prepare_id", ""))
        parts += [p.get("amount", ""), action, p.get("sign_time", "")]
        return hashlib.md5("".join(str(x) for x in parts).encode()).hexdigest()

    def verify_form(self, p: dict) -> bool:
        return hmac.compare_digest(self.sign(p, str(p.get("action", ""))), str(p.get("sign_string", "")))


class StarsProvider(Provider):
    """Telegram Stars (XTR) - raqamli tovarlar uchun Telegramning rasmiy to'lov usuli."""
    code, name, kind = "stars", "Telegram Stars", "stars"

    def configured(self) -> bool:
        return bool(settings.bot_token) and settings.stars_enabled

    async def create_payment(self, topup, user) -> dict:  # invoice havolasi router'da bot orqali yaratiladi
        return {"type": "invoice", "stars": topup.stars_amount}


PROVIDERS: dict[str, Provider] = {p.code: p for p in (StarsProvider(), ManualCardProvider(), ClickProvider(), MockProvider())}
