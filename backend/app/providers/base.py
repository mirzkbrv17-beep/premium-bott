from dataclasses import dataclass
from typing import Optional


@dataclass
class PaymentEvent:
    event_id: str
    topup_public_id: str
    status: str  # success | failed | canceled
    paid_amount: int  # UZS yoki XTR (paid_unit)
    paid_unit: str = "UZS"
    external_id: Optional[str] = None


class Provider:
    code = ""
    name = ""
    kind = "external"  # external (webhook) | manual | stars

    def configured(self) -> bool:
        return False

    def status(self) -> str:
        return "ready" if self.configured() else "not_configured"

    async def create_payment(self, topup, user) -> dict:
        raise NotImplementedError

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        return False

    def parse_webhook(self, body: bytes) -> PaymentEvent:
        raise NotImplementedError
