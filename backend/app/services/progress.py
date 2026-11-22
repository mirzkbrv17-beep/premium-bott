"""XP, level, VIP, achievements."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Achievement, DailyBonusClaim, GiftTransfer, Order, Referral, Rental, TopUp, User,
                      UserAchievement, VIPTier, XpEvent)
from . import settings_svc
from .notify import notify


async def add_xp(session: AsyncSession, user_id: int, amount: int, reason: str) -> None:
    if amount <= 0:
        return
    session.add(XpEvent(user_id=user_id, amount=amount, reason=reason))
    user = await session.get(User, user_id, with_for_update=True)
    user.xp += amount
    await session.flush()


def level_of(xp: int, per_level: int = 100) -> dict:
    lvl = xp // per_level + 1
    return {"level": lvl, "xp": xp, "xp_in_level": xp % per_level, "xp_for_next": per_level}


async def vip_for(session: AsyncSession, user: User) -> dict:
    tiers = (await session.execute(select(VIPTier).where(VIPTier.active.is_(True)).order_by(VIPTier.rank))).scalars().all()
    current = None
    for t in tiers:  # server hisoblaydi - frontendga ishonilmaydi
        if user.spent_uzs_total >= t.min_spent_uzs:
            current = t
    nxt = next((t for t in tiers if current is None or t.rank > current.rank), None)
    ser = lambda t: None if t is None else {"id": t.id, "name": t.name, "rank": t.rank, "badge": t.badge,
                                            "min_spent_uzs": t.min_spent_uzs, "discount_percent": t.discount_percent,
                                            "perks": t.perks}
    return {"current": ser(current), "next": ser(nxt), "spent_uzs": user.spent_uzs_total,
            "tiers": [ser(t) for t in tiers]}


async def vip_discount_percent(session: AsyncSession, user: User) -> int:
    v = await vip_for(session, user)
    return v["current"]["discount_percent"] if v["current"] else 0


async def metrics(session: AsyncSession, user: User) -> dict:
    cnt = lambda q: session.scalar(q)
    return {
        "orders": await cnt(select(func.count(Order.id)).where(Order.user_id == user.id, Order.status.notin_(["cancelled", "refunded"]))),
        "topups": await cnt(select(func.count(TopUp.id)).where(TopUp.user_id == user.id, TopUp.status == "success")),
        "streak": await cnt(select(func.coalesce(func.max(DailyBonusClaim.streak), 0)).where(DailyBonusClaim.user_id == user.id)),
        "referrals": await cnt(select(func.count(Referral.id)).where(Referral.referrer_id == user.id, Referral.status == "rewarded")),
        "xp": user.xp,
        "spent_uzs": user.spent_uzs_total,
        "gifts": await cnt(select(func.count(GiftTransfer.id)).where(GiftTransfer.sender_id == user.id, GiftTransfer.status == "completed")),
        "rentals": await cnt(select(func.count(Rental.id)).where(Rental.user_id == user.id, Rental.status != "cancelled")),
    }


async def check_achievements(session: AsyncSession, user: User) -> list[str]:
    """Yangi ochilgan achievementlarni belgilaydi (idempotent: unique constraint)."""
    m = await metrics(session, user)
    have = set((await session.execute(select(UserAchievement.achievement_id).where(UserAchievement.user_id == user.id))).scalars())
    unlocked = []
    for a in (await session.execute(select(Achievement).where(Achievement.active.is_(True)))).scalars():
        if a.id not in have and m.get(a.metric, 0) >= a.threshold:
            session.add(UserAchievement(user_id=user.id, achievement_id=a.id))
            await session.flush()
            await add_xp(session, user.id, a.xp_reward, "achievement")
            await notify(session, user.id, "bonus", f"{a.icon} Yangi yutuq: {a.title}", a.description,
                         dedupe_key=f"ach:{user.id}:{a.id}")
            unlocked.append(a.code)
    return unlocked
