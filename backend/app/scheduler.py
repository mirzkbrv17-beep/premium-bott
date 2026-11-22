"""Davriy ishlar. Barcha holat DB'da (restartda yo'qolmaydi); skip_locked ko'p instansda takrorni oldini oladi."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from .db import SessionLocal
from .models import Notification, User
from .services import bonus, shop
from .timeutil import now_utc

log = logging.getLogger("abu.sched")
_sched: AsyncIOScheduler | None = None


async def job_referrals():
    async with SessionLocal() as s, s.begin():
        n = await bonus.process_pending_referrals(s)
        if n:
            log.info("referral mukofotlari: %s", n)


async def job_rentals():
    async with SessionLocal() as s, s.begin():
        await shop.tick_rentals(s)


async def job_deliver_notifications():
    from .bot import instance
    if instance.bot is None:
        return
    async with SessionLocal() as s, s.begin():
        rows = (await s.execute(select(Notification).where(Notification.sent_at.is_(None), Notification.send_attempts < 3)
                                .order_by(Notification.id).limit(50).with_for_update(skip_locked=True))).scalars().all()
        for n in rows:
            u = await s.get(User, n.user_id)
            prefs = ((u.profile.settings or {}).get("notifications") or {}) if u and u.profile else {}
            if not u or not u.telegram_id or prefs.get(n.type, True) is False:
                n.sent_at = now_utc()  # foydalanuvchi o'chirgan - botga yuborilmaydi (ilovada ko'rinadi)
                continue
            n.send_attempts += 1
            if await instance.send_text(u.telegram_id, f"<b>{n.title}</b>\n{n.body}"):
                n.sent_at = now_utc()


def start() -> None:
    global _sched
    _sched = AsyncIOScheduler(timezone="UTC")
    _sched.add_job(job_referrals, "interval", seconds=60, id="ref", max_instances=1, coalesce=True)
    _sched.add_job(job_rentals, "interval", seconds=60, id="rent", max_instances=1, coalesce=True)
    _sched.add_job(job_deliver_notifications, "interval", seconds=20, id="notif", max_instances=1, coalesce=True)
    _sched.start()


def stop() -> None:
    if _sched:
        _sched.shutdown(wait=False)
