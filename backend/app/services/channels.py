"""Majburiy kanallar obunasini server orqali tekshirish (bot get_chat_member)."""
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MandatoryChannel
from . import settings_svc

# bot.py o'rnatadi: (chat_id, telegram_id) -> True/False/None(noma'lum)
MemberChecker = Callable[[str, int], Awaitable[Optional[bool]]]
_checker: Optional[MemberChecker] = None


def set_member_checker(fn: Optional[MemberChecker]) -> None:
    global _checker
    _checker = fn


async def check_subscription(session: AsyncSession, telegram_id: Optional[int]) -> dict:
    """{ok, missing:[channel], unverifiable:bool}. Talab o'chiq yoki kanal yo'q bo'lsa ok=True."""
    if not await settings_svc.get(session, "require_subscription", True):
        return {"ok": True, "missing": [], "unverifiable": False}
    chans = (await session.execute(select(MandatoryChannel).where(MandatoryChannel.active.is_(True))
                                   .order_by(MandatoryChannel.sort, MandatoryChannel.id))).scalars().all()
    if not chans:
        return {"ok": True, "missing": [], "unverifiable": False}
    missing, unverifiable = [], False
    for c in chans:
        res = None
        if _checker is not None and telegram_id:
            try:
                res = await _checker(c.chat_id, telegram_id)
            except Exception:
                res = None
        if res is None:
            unverifiable = True
        elif res is False:
            missing.append(c)
    return {"ok": not missing and not unverifiable, "missing": missing, "unverifiable": unverifiable}


def channel_dict(c: MandatoryChannel) -> dict:
    url = c.invite_url or (f"https://t.me/{c.chat_id.lstrip('@')}" if not c.chat_id.startswith("-") else None)
    return {"id": c.id, "chat_id": c.chat_id, "title": c.title or c.chat_id, "url": url}
