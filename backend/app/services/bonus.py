"""Kunlik bonus, referral mukofoti, promo kod."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..models import (ABU_F, ABU_TON, CURRENCIES, DailyBonusClaim, PromoCode, PromoRedemption, Referral, User)
from ..timeutil import now_utc, tashkent_date
from . import channels, ledger, settings_svc
from .notify import notify
from .progress import add_xp, check_achievements


# ------------------------------------------------------------------ kunlik bonus
def ladder_amount(ladder: list, streak: int) -> int:
    """Streak 30 kunlik sikl bo'yicha; amount = streak'dan oshmagan eng yuqori bosqich."""
    pos = ((streak - 1) % 30) + 1
    amt = 0
    for day, a in sorted(ladder):
        if pos >= day:
            amt = a
    return amt


async def daily_state(session: AsyncSession, user_id: int, now: datetime | None = None) -> dict:
    today = tashkent_date(now)
    last = (await session.execute(select(DailyBonusClaim).where(DailyBonusClaim.user_id == user_id)
                                  .order_by(DailyBonusClaim.claim_date.desc()).limit(1))).scalar_one_or_none()
    ladder = await settings_svc.get(session, "daily_bonus_ladder")
    claimed = bool(last and last.claim_date == today)
    cur = last.streak if last and last.claim_date >= today - timedelta(days=1) else 0
    nxt_streak = cur if claimed else cur + 1
    return {"claimed_today": claimed, "streak": cur, "next_amount": ladder_amount(ladder, max(nxt_streak, 1)),
            "ladder": ladder, "today": today.isoformat()}


async def claim_daily(session: AsyncSession, user_id: int, now: datetime | None = None) -> dict:
    user = await session.get(User, user_id, with_for_update=True)  # bir foydalanuvchi so'rovlarini ketma-ketlashtiradi
    today = tashkent_date(now)
    last = (await session.execute(select(DailyBonusClaim).where(DailyBonusClaim.user_id == user_id)
                                  .order_by(DailyBonusClaim.claim_date.desc()).limit(1))).scalar_one_or_none()
    if last and last.claim_date == today:
        raise DomainError("already_claimed", "Bugungi bonus allaqachon olingan", 409)
    streak = last.streak + 1 if last and last.claim_date == today - timedelta(days=1) else 1
    amount = ladder_amount(await settings_svc.get(session, "daily_bonus_ladder"), streak)
    session.add(DailyBonusClaim(user_id=user_id, claim_date=today, streak=streak, amount=amount))
    await session.flush()
    entry, _ = await ledger.post_entry(session, user_id=user_id, currency=ABU_F, amount=amount, kind="bonus_daily",
                                       idem=f"daily:{user_id}:{today.isoformat()}", ref_type="daily", ref_id=today.isoformat())
    await add_xp(session, user_id, 5, "daily")
    await check_achievements(session, user)
    return {"amount": amount, "currency": ABU_F, "streak": streak, "tx_id": entry.tx_id}


# ------------------------------------------------------------------ referral
async def process_pending_referrals(session: AsyncSession, limit: int = 50) -> int:
    """Scheduler chaqiradi. Har bir referral FAQAT bir marta mukofotlanadi (status + idempotency)."""
    rows = (await session.execute(select(Referral).where(Referral.status == "pending", Referral.qualifies_at <= now_utc())
                                  .order_by(Referral.id).limit(limit).with_for_update(skip_locked=True))).scalars().all()
    done = 0
    for r in rows:
        invited = await session.get(User, r.invited_id)
        if invited.is_banned or invited.is_bot:
            r.status, r.note = "rejected", "taklif qilingan foydalanuvchi mos emas"
            continue
        sub = await channels.check_subscription(session, invited.telegram_id)  # serverda qayta tekshiruv
        if not sub["ok"]:
            if now_utc() - r.qualifies_at > timedelta(days=3):
                r.status, r.note = "rejected", "majburiy obuna bajarilmadi"
            continue
        f = int(await settings_svc.get(session, "referral_reward_f"))
        ton = int(await settings_svc.get(session, "referral_reward_ton"))
        if f > 0:
            await ledger.post_entry(session, user_id=r.referrer_id, currency=ABU_F, amount=f, kind="bonus_referral",
                                    idem=f"referral:{r.id}:F", ref_type="referral", ref_id=str(r.id))
        if ton > 0:
            await ledger.post_entry(session, user_id=r.referrer_id, currency=ABU_TON, amount=ton, kind="bonus_referral",
                                    idem=f"referral:{r.id}:TON", ref_type="referral", ref_id=str(r.id))
        r.status, r.rewarded_at = "rewarded", now_utc()
        await add_xp(session, r.referrer_id, 20, "referral")
        await notify(session, r.referrer_id, "referral", "🎉 Referral mukofoti", f"+{f} ABU F, +{ton} ABU TON",
                     dedupe_key=f"ref-rw:{r.id}")
        await check_achievements(session, await session.get(User, r.referrer_id))
        done += 1
    await session.flush()
    return done


# ------------------------------------------------------------------ promo
def validate_promo_payload(d: dict) -> None:
    mode = d.get("mode")
    if mode not in ("limited_uses", "time_limited", "unlimited"):
        raise DomainError("bad_promo", "Rejim noto'g'ri")
    if d.get("currency") not in CURRENCIES or int(d.get("amount") or 0) <= 0:
        raise DomainError("bad_promo", "Valyuta yoki miqdor noto'g'ri")
    mu, ex = d.get("max_uses"), d.get("expires_at")
    if mode == "limited_uses" and (not mu or ex):
        raise DomainError("bad_promo", "Limitli rejimda foydalanish soni kerak, muddat bo'lmasin")
    if mode == "time_limited" and (not ex or mu):
        raise DomainError("bad_promo", "Muddatli rejimda muddat kerak, foydalanish limiti bo'lmasin")
    if mode == "unlimited" and (mu or ex):
        raise DomainError("bad_promo", "Cheksiz rejimda na muddat, na limit bo'lmasin")


async def redeem_promo(session: AsyncSession, user: User, code: str) -> dict:
    code = (code or "").strip().upper()
    p = (await session.execute(select(PromoCode).where(PromoCode.code == code).with_for_update())).scalar_one_or_none()
    if p is None or not p.active or p.deleted_at is not None:
        raise DomainError("promo_invalid", "Promo kod topilmadi yoki faol emas", 404)
    used = await session.scalar(select(PromoRedemption.id).where(PromoRedemption.user_id == user.id, PromoRedemption.promo_id == p.id))
    if used:
        raise DomainError("promo_used", "Bu promo kodni allaqachon ishlatgansiz", 409)
    if p.mode == "time_limited" and (p.expires_at is None or p.expires_at <= now_utc()):
        raise DomainError("promo_expired", "Promo kod muddati tugagan", 410)
    if p.mode == "limited_uses" and p.used_count >= (p.max_uses or 0):
        raise DomainError("promo_exhausted", "Promo kod limiti tugagan", 410)
    session.add(PromoRedemption(user_id=user.id, promo_id=p.id))
    p.used_count += 1
    await session.flush()
    entry, _ = await ledger.post_entry(session, user_id=user.id, currency=p.currency, amount=p.amount, kind="bonus_promo",
                                       idem=f"promo:{p.id}:{user.id}", ref_type="promo", ref_id=p.code)
    await notify(session, user.id, "promo", "🎁 Promo kod qo'llandi", f"+{p.amount} {p.currency.replace('_', ' ')}")
    return {"amount": p.amount, "currency": p.currency, "tx_id": entry.tx_id}
