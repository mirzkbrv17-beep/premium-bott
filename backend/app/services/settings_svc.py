"""AppSetting: admin o'zgartira oladigan sozlamalar (default qiymatlar bilan)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AppSetting

DEFAULTS: dict = {
    "abu_f_uzs_per_unit": 10,  # 5 000 ABU F = 50 000 UZS
    "abu_f_min_units": 5,
    "uzs_per_star": 240,  # Stars invoys narxi uchun (admin o'zgartiradi)
    "daily_bonus_ladder": [[1, 5], [3, 10], [7, 25], [14, 50], [30, 100]],
    "referral_reward_f": 50,
    "referral_reward_ton": 2,
    "referral_wait_minutes": 120,
    "referral_daily_cap": 30,
    "require_subscription": True,
    "gift_min_account_age_hours": 24,
    "gift_daily_limit": {"ABU_F": 5000, "ABU_TON": 100},
    "gift_review_threshold": {"ABU_F": 2000, "ABU_TON": 50},
    "market_commission_percent": 5,
    "market_requires_moderation": True,
    "market_max_active_listings": 20,
    "market_promo_cost": {"currency": "ABU_F", "amount": 50, "days": 3},
    "rental_remind_hours": 24,
    "daily_question_xp": 10,
    "xp_per_level": 100,
    "faq": [
        {"q": "ABU F nima?", "a": "ABU F - ABU BOT ichki virtual valyutasi. Naqd pul emas va pulga yechib olinmaydi."},
        {"q": "Buyurtmam qachon bajariladi?", "a": "To'lovdan keyin buyurtma 'jarayonda' holatiga o'tadi va admin tomonidan topshiriladi."},
        {"q": "Ijarani qanday qaytaraman?", "a": "Muddat tugagach buyum qaytarilishi admin tomonidan tekshiriladi."},
    ],
}


async def get(session: AsyncSession, key: str, default=None):
    row = await session.get(AppSetting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, default)


async def put(session: AsyncSession, key: str, value) -> None:
    row = await session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    await session.flush()


async def all_settings(session: AsyncSession) -> dict:
    out = dict(DEFAULTS)
    for r in (await session.execute(select(AppSetting))).scalars():
        out[r.key] = r.value
    return out
