"""Telegram initData tekshiruvi, imzolangan sessiya tokenlari."""
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .config import settings
from .errors import DomainError


def verify_init_data(init_data: str, bot_token: str | None = None, max_age: int | None = None) -> dict:
    """Telegram WebApp initData imzosini tekshiradi va foydalanuvchi ma'lumotini qaytaradi."""
    bot_token = bot_token if bot_token is not None else settings.bot_token
    max_age = max_age if max_age is not None else settings.init_data_max_age
    if not bot_token or not init_data:
        raise DomainError("auth_failed", "Autentifikatsiya sozlanmagan", 401)
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise DomainError("auth_failed", "initData noto'g'ri", 401)
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise DomainError("auth_failed", "initData imzosi noto'g'ri", 401)
    try:
        auth_date = int(pairs.get("auth_date", "0"))
        user = json.loads(pairs["user"])
    except Exception:
        raise DomainError("auth_failed", "initData noto'g'ri", 401)
    if time.time() - auth_date > max_age:
        raise DomainError("auth_failed", "initData muddati o'tgan", 401)
    if "id" not in user:
        raise DomainError("auth_failed", "initData noto'g'ri", 401)
    return {"user": user, "start_param": pairs.get("start_param")}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(payload: dict, ttl: int, purpose: str = "session") -> str:
    body = dict(payload, exp=int(time.time()) + ttl, p=purpose)
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def read_token(token: str, purpose: str = "session") -> dict:
    try:
        raw, sig = token.split(".", 1)
        good = _b64(hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, sig):
            raise ValueError
        body = json.loads(_unb64(raw))
        if body.get("p") != purpose or body["exp"] < time.time():
            raise ValueError
        return body
    except Exception:
        raise DomainError("auth_failed", "Sessiya yaroqsiz yoki muddati tugagan", 401)
