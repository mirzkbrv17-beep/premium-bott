from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as cfg
from ..models import AdminUser, Referral, Role, User, UserProfile
from ..timeutil import now_utc
from . import settings_svc
from .ledger import ensure_accounts


async def _bootstrap_admin(session: AsyncSession, user: User) -> None:
    if user.telegram_id and user.telegram_id in cfg.admin_ids:
        if (await session.execute(select(AdminUser).where(AdminUser.user_id == user.id))).scalar_one_or_none() is None:
            role = (await session.execute(select(Role).where(Role.name == "superadmin"))).scalar_one_or_none()
            if role:
                session.add(AdminUser(user_id=user.id, role_id=role.id))
                await session.flush()


async def get_or_create_telegram_user(session: AsyncSession, tg: dict, start_param: str | None = None) -> tuple[User, bool]:
    tid = int(tg["id"])
    user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    created = False
    if user is None:
        try:
            async with session.begin_nested():
                user = User(telegram_id=tid, first_name=tg.get("first_name", "") or "", last_name=tg.get("last_name"),
                            username=tg.get("username"), photo_url=tg.get("photo_url"),
                            language_code=tg.get("language_code"), is_bot=bool(tg.get("is_bot")))
                session.add(user)
                await session.flush()
                session.add(UserProfile(user=user, settings={}))
                await session.flush()
            created = True
        except IntegrityError:  # parallel /start - boshqasi yaratib bo'ldi
            user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one()
    else:
        user.first_name = tg.get("first_name", user.first_name) or user.first_name
        user.last_name = tg.get("last_name")
        user.username = tg.get("username")
        user.photo_url = tg.get("photo_url") or user.photo_url
    user.last_seen_at = now_utc()
    await ensure_accounts(session, user.id)
    if created and start_param and start_param.startswith("ref_"):
        await register_referral(session, user, start_param[4:])
    await _bootstrap_admin(session, user)
    return user, created


async def register_referral(session: AsyncSession, invited: User, code: str) -> Referral | None:
    """Faqat yangi foydalanuvchi uchun, bir marta. Mukofot keyin (shartlar bajarilgach) beriladi."""
    referrer = (await session.execute(select(User).where(User.referral_code == code.upper(), User.kind == "user"))).scalar_one_or_none()
    if referrer is None or referrer.id == invited.id or invited.is_bot:
        return None
    wait = int(await settings_svc.get(session, "referral_wait_minutes", 120))
    cap = int(await settings_svc.get(session, "referral_daily_cap", 30))
    since = now_utc() - timedelta(days=1)
    recent = await session.scalar(select(func.count(Referral.id)).where(Referral.referrer_id == referrer.id, Referral.created_at >= since))
    ref = Referral(referrer_id=referrer.id, invited_id=invited.id, qualifies_at=now_utc() + timedelta(minutes=wait),
                   status="flagged" if recent >= cap else "pending",
                   note="kunlik limit oshdi" if recent >= cap else None)
    invited.referred_by_id = referrer.id
    session.add(ref)
    await session.flush()
    return ref


def public_user(u: User) -> dict:
    return {"abu_id": u.abu_id, "first_name": u.first_name, "last_name": u.last_name, "username": u.username,
            "photo_url": u.photo_url, "created_at": u.created_at.isoformat() if u.created_at else None}
