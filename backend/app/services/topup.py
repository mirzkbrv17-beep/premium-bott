"""Balans to'ldirish: yaratish, webhook qayta ishlash (idempotent), admin qo'lda tasdiq."""
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError, forbidden, not_found
from ..models import ABU_F, ABU_TON, PaymentProvider, TonPackage, TopUp, User, WebhookEvent, utcnow
from ..providers.base import PaymentEvent
from ..providers.impls import PROVIDERS
from ..timeutil import ceil_div
from . import audit, ledger, settings_svc
from .notify import notify
from .progress import add_xp, check_achievements

MAX_PENDING = 5


async def options(session: AsyncSession) -> dict:
    rows = {p.code: p for p in (await session.execute(select(PaymentProvider))).scalars()}
    provs = []
    for code, impl in PROVIDERS.items():
        row = rows.get(code)
        if code == "mock" and impl.status() != "ready":
            continue
        provs.append({"code": code, "name": impl.name, "status": impl.status(), "enabled": bool(row.enabled) if row else True,
                      "kind": impl.kind})
    pk = (await session.execute(select(TonPackage).where(TonPackage.active.is_(True)).order_by(TonPackage.sort, TonPackage.units))).scalars().all()
    return {"abu_f": {"uzs_per_unit": await settings_svc.get(session, "abu_f_uzs_per_unit"),
                      "min_units": await settings_svc.get(session, "abu_f_min_units")},
            "abu_ton_packages": [{"id": p.id, "units": p.units, "price_uzs": p.price_uzs} for p in pk],
            "uzs_per_star": await settings_svc.get(session, "uzs_per_star"), "providers": provs}


async def create_topup(session: AsyncSession, user: User, *, currency: str, provider: str, idem: str,
                       units: int | None = None, package_id: int | None = None) -> tuple[TopUp, bool]:
    existing = (await session.execute(select(TopUp).where(TopUp.user_id == user.id, TopUp.idempotency_key == idem))).scalar_one_or_none()
    if existing:
        return existing, False
    impl = PROVIDERS.get(provider)
    row = await session.get(PaymentProvider, provider)
    if impl is None or (row is not None and not row.enabled):
        raise DomainError("provider_disabled", "To'lov usuli mavjud emas", 400)
    if impl.status() != "ready":
        raise DomainError("provider_not_configured", f"{impl.name}: hali sozlanmagan (not_configured)", 409)
    if currency == ABU_F:
        rate = int(await settings_svc.get(session, "abu_f_uzs_per_unit"))
        mn = int(await settings_svc.get(session, "abu_f_min_units"))
        if not units or units < mn or units > 100_000_000:
            raise DomainError("bad_amount", f"Minimal xarid: {mn} ABU F")
        uzs = units * rate
    elif currency == ABU_TON:
        pkg = await session.get(TonPackage, package_id) if package_id else None
        if not pkg or not pkg.active:
            raise DomainError("bad_package", "ABU TON paketini tanlang")
        units, uzs, rate = pkg.units, pkg.price_uzs, ceil_div(pkg.price_uzs, pkg.units)
    else:
        raise DomainError("bad_currency", "Noma'lum valyuta")
    pend = await session.scalar(select(func.count(TopUp.id)).where(TopUp.user_id == user.id, TopUp.status.in_(["pending", "awaiting_review"])))
    if pend >= MAX_PENDING:
        raise DomainError("too_many_pending", "Kutilayotgan to'lovlar ko'p. Avval ularni yakunlang.", 429)
    stars = None
    if provider == "stars":
        stars = ceil_div(uzs, int(await settings_svc.get(session, "uzs_per_star")))
    t = TopUp(user_id=user.id, currency=currency, units=units, uzs_amount=uzs, rate_snapshot=rate, provider=provider,
              idempotency_key=idem, stars_amount=stars, status="pending")
    session.add(t)
    await session.flush()
    return t, True


async def _credit(session: AsyncSession, t: TopUp, *, admin_id: int | None = None) -> None:
    entry, _ = await ledger.post_entry(session, user_id=t.user_id, currency=t.currency, amount=t.units, kind="topup",
                                       idem=f"topup:{t.public_id}", ref_type="topup", ref_id=t.public_id, admin_id=admin_id,
                                       meta={"provider": t.provider, "uzs": t.uzs_amount})
    t.status, t.ledger_tx_id = "success", entry.tx_id
    user = await session.get(User, t.user_id)
    await add_xp(session, t.user_id, max(1, t.uzs_amount // 10_000), "topup")
    await check_achievements(session, user)
    await notify(session, t.user_id, "payment", "✅ To'lov qabul qilindi",
                 f"+{t.units:,} {t.currency.replace('_', ' ')}".replace(",", " "), dedupe_key=f"topup-ok:{t.public_id}")


async def process_event(session: AsyncSession, provider: str, ev: PaymentEvent) -> str:
    """Provayder hodisasini bir marta qayta ishlaydi. Qaytaradi: processed|duplicate|already_processed."""
    try:
        async with session.begin_nested():
            session.add(WebhookEvent(provider=provider, event_id=ev.event_id, result="received"))
            await session.flush()
    except IntegrityError:
        return "duplicate"
    t = (await session.execute(select(TopUp).where(TopUp.public_id == ev.topup_public_id).with_for_update())).scalar_one_or_none()
    if t is None:
        raise not_found("To'lov topilmadi")
    if t.provider != provider:
        raise DomainError("provider_mismatch", "To'lov provayderi mos emas")
    expected, unit = (t.stars_amount, "XTR") if provider == "stars" else (t.uzs_amount, "UZS")
    if ev.paid_unit != unit or ev.paid_amount != expected:
        raise DomainError("amount_mismatch", "To'lov summasi yoki valyutasi mos emas")
    if t.status == "success":
        return "already_processed"
    if ev.status == "success":
        if t.status not in ("pending", "awaiting_review"):
            raise DomainError("bad_state", "To'lov holati muvaffaqiyatga o'tkazib bo'lmaydi")
        t.external_id = ev.external_id or ev.event_id
        await _credit(session, t)
    elif ev.status in ("failed", "canceled") and t.status in ("pending", "awaiting_review"):
        t.status = ev.status
    return "processed"


async def attach_receipt(session: AsyncSession, t: TopUp, data: bytes, mime: str) -> None:
    """Foydalanuvchi chek yuklaydi -> 'awaiting_review'. Balans AVTOMATIK qo'shilmaydi."""
    if t.provider != "manual_card" or t.status not in ("pending", "awaiting_review"):
        raise DomainError("bad_state", "Bu to'lovga chek biriktirib bo'lmaydi")
    t.receipt_data, t.receipt_mime, t.status = data, mime, "awaiting_review"
    await session.flush()


async def admin_review(session: AsyncSession, topup_id: int, *, approve: bool, admin_id: int, note: str | None, ip=None) -> TopUp:
    t = (await session.execute(select(TopUp).where(TopUp.id == topup_id).with_for_update())).scalar_one_or_none()
    if t is None:
        raise not_found("To'lov topilmadi")
    if t.provider != "manual_card":
        raise forbidden("Faqat qo'lda to'lovlarni admin tasdiqlay oladi; boshqalari provayder webhooki orqali")
    if t.status not in ("pending", "awaiting_review"):
        raise DomainError("already_processed", "Bu to'lov allaqachon ko'rib chiqilgan", 409)
    t.reviewed_by, t.reviewed_at, t.review_note = admin_id, utcnow(), note
    if approve:
        await _credit(session, t, admin_id=admin_id)
    else:
        t.status = "failed"
        await notify(session, t.user_id, "payment", "❌ To'lov rad etildi", note or "", dedupe_key=f"topup-rej:{t.public_id}")
    await audit.log(session, admin_id, "topup.approve" if approve else "topup.reject", "topup", t.public_id,
                    {"uzs": t.uzs_amount, "units": t.units, "note": note}, ip)
    return t
