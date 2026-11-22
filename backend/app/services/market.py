"""ABU MARKET. Escrow faqat ichki virtual balans (ledger) ichida ishlaydi: haqiqiy pul ushlab turilmaydi/yechilmaydi."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError, forbidden, not_found
from ..models import (CURRENCIES, Dispute, MarketListing, MarketMessage, MarketOrder, Review, SellerProfile, User, utcnow)
from ..timeutil import now_utc
from . import audit, ledger, settings_svc
from .notify import notify
from .progress import add_xp, check_achievements

CATEGORIES = ("abu_f", "abu_ton", "stars", "gift", "nft", "premium", "voucher", "sticker", "other")


async def system_user(session: AsyncSession, name: str) -> User:
    abu_id = f"SYS-{name.upper()}"
    u = (await session.execute(select(User).where(User.abu_id == abu_id))).scalar_one_or_none()
    if u is None:
        u = User(abu_id=abu_id, kind="system", first_name=f"ABU {name}", referral_code=f"SYS{name[:4].upper()}")
        session.add(u)
        await session.flush()
        await ledger.ensure_accounts(session, u.id)
    return u


async def seller_profile(session: AsyncSession, user: User) -> SellerProfile:
    sp = await session.get(SellerProfile, user.id)
    if sp is None:
        sp = SellerProfile(user_id=user.id, display_name=user.first_name or user.abu_id)
        session.add(sp)
        await session.flush()
    return sp


def _check(d: dict) -> None:
    if d.get("category") not in CATEGORIES:
        raise DomainError("bad_category", "Kategoriya noto'g'ri")
    if d.get("price_currency") not in CURRENCIES:
        raise DomainError("bad_currency", "Narx valyutasi ABU F yoki ABU TON bo'lishi kerak")
    if not (1 <= int(d.get("price_amount", 0)) <= 10_000_000_000) or not (1 <= int(d.get("quantity", 1)) <= 100000):
        raise DomainError("bad_amount", "Narx yoki soni noto'g'ri")
    if not (3 <= len((d.get("title") or "").strip()) <= 120):
        raise DomainError("bad_title", "Sarlavha 3-120 belgi bo'lsin")


async def create_listing(session: AsyncSession, user: User, d: dict) -> MarketListing:
    _check(d)
    sp = await seller_profile(session, user)
    if sp.banned:
        raise forbidden("Sotuvchi sifatida cheklangansiz")
    active = await session.scalar(select(func.count(MarketListing.id)).where(MarketListing.seller_id == user.id, MarketListing.status.in_(["active", "pending"])))
    if active >= int(await settings_svc.get(session, "market_max_active_listings")):
        raise DomainError("limit", "Faol e'lonlar limiti tugadi")
    needs = await settings_svc.get(session, "market_requires_moderation")
    li = MarketListing(seller_id=user.id, category=d["category"], title=d["title"].strip(), description=(d.get("description") or "")[:2000],
                       price_amount=int(d["price_amount"]), price_currency=d["price_currency"], quantity=int(d.get("quantity", 1)),
                       status="pending" if needs else "active")
    session.add(li)
    await session.flush()
    return li


async def update_listing(session: AsyncSession, user: User, li: MarketListing, d: dict) -> MarketListing:
    if li.seller_id != user.id:
        raise forbidden()
    if li.status in ("removed", "rejected"):
        raise DomainError("bad_state", "Bu e'lonni tahrirlab bo'lmaydi", 409)
    merged = {k: d.get(k, getattr(li, k)) for k in ("category", "title", "price_amount", "price_currency", "quantity")}
    _check(merged)
    for k, v in merged.items():
        setattr(li, k, v)
    if "description" in d:
        li.description = (d["description"] or "")[:2000]
    if await settings_svc.get(session, "market_requires_moderation") and li.status == "active":
        li.status = "pending"  # o'zgargan e'lon qayta moderatsiyadan o'tadi
    return li


async def toggle_listing(li: MarketListing, user: User) -> MarketListing:
    if li.seller_id != user.id:
        raise forbidden()
    if li.status == "active":
        li.status = "hidden"
    elif li.status in ("hidden", "sold_out") and li.quantity > 0:
        li.status = "active"
    else:
        raise DomainError("bad_state", "Holatni o'zgartirib bo'lmaydi", 409)
    return li


async def promote(session: AsyncSession, user: User, li: MarketListing) -> MarketListing:
    if li.seller_id != user.id or li.status != "active":
        raise DomainError("bad_state", "Faqat faol e'lonni targ'ib qilish mumkin", 409)
    cost = await settings_svc.get(session, "market_promo_cost")
    plat = await system_user(session, "platform")
    key = f"promo:{li.id}:{int((li.promoted_until or now_utc()).timestamp())}"
    await ledger.post_entry(session, user_id=user.id, currency=cost["currency"], amount=-int(cost["amount"]), kind="market_promo", idem=key, ref_type="listing", ref_id=li.public_id)
    await ledger.post_entry(session, user_id=plat.id, currency=cost["currency"], amount=int(cost["amount"]), kind="market_promo", idem=key + ":in", ref_type="listing", ref_id=li.public_id)
    li.promoted_until = max(li.promoted_until or now_utc(), now_utc()) + timedelta(days=int(cost["days"]))
    return li


async def buy(session: AsyncSession, buyer: User, listing_id: int, qty: int, idem: str) -> tuple[MarketOrder, bool]:
    ex = (await session.execute(select(MarketOrder).where(MarketOrder.buyer_id == buyer.id, MarketOrder.idempotency_key == idem))).scalar_one_or_none()
    if ex:
        return ex, False
    li = (await session.execute(select(MarketListing).where(MarketListing.id == listing_id).with_for_update())).scalar_one_or_none()
    if not li or li.status != "active":
        raise DomainError("unavailable", "E'lon mavjud emas", 404)
    if li.seller_id == buyer.id:
        raise DomainError("self_buy", "O'z e'loningizni sotib ola olmaysiz")
    sp = await seller_profile(session, await session.get(User, li.seller_id))
    if sp.banned:
        raise DomainError("unavailable", "Sotuvchi cheklangan", 409)
    if qty < 1 or qty > li.quantity:
        raise DomainError("out_of_stock", "Yetarli miqdor yo'q", 409)
    amount = li.price_amount * qty
    pct = int(await settings_svc.get(session, "market_commission_percent"))
    mo = MarketOrder(listing_id=li.id, buyer_id=buyer.id, seller_id=li.seller_id, qty=qty, amount=amount, currency=li.price_currency,
                     commission=amount * pct // 100, idempotency_key=idem, title=li.title)
    session.add(mo)
    await session.flush()
    esc = await system_user(session, "escrow")
    await ledger.post_entry(session, user_id=buyer.id, currency=mo.currency, amount=-amount, kind="market_hold", idem=f"mo:{mo.public_id}:hold", ref_type="market_order", ref_id=mo.public_id)
    await ledger.post_entry(session, user_id=esc.id, currency=mo.currency, amount=amount, kind="market_hold", idem=f"mo:{mo.public_id}:hold-in", ref_type="market_order", ref_id=mo.public_id)
    li.quantity -= qty
    if li.quantity == 0:
        li.status = "sold_out"
    await notify(session, li.seller_id, "market", "🛍 Yangi buyurtma", f"{li.title} x{qty}")
    return mo, True


async def _get_order(session: AsyncSession, oid: int) -> MarketOrder:
    mo = (await session.execute(select(MarketOrder).where(MarketOrder.id == oid).with_for_update())).scalar_one_or_none()
    if not mo:
        raise not_found()
    return mo


async def _release(session: AsyncSession, mo: MarketOrder) -> None:
    esc, plat = await system_user(session, "escrow"), await system_user(session, "platform")
    k = f"mo:{mo.public_id}:release"
    await ledger.post_entry(session, user_id=esc.id, currency=mo.currency, amount=-mo.amount, kind="market_release", idem=k + ":out", ref_type="market_order", ref_id=mo.public_id)
    await ledger.post_entry(session, user_id=mo.seller_id, currency=mo.currency, amount=mo.amount - mo.commission, kind="market_release", idem=k + ":seller", ref_type="market_order", ref_id=mo.public_id)
    if mo.commission:
        await ledger.post_entry(session, user_id=plat.id, currency=mo.currency, amount=mo.commission, kind="commission", idem=k + ":fee", ref_type="market_order", ref_id=mo.public_id)
    mo.status = "completed"
    sp = await seller_profile(session, await session.get(User, mo.seller_id))
    sp.sales_count += 1
    await notify(session, mo.seller_id, "market", "💰 Buyurtma yakunlandi", f"+{mo.amount - mo.commission} {mo.currency.replace('_', ' ')}", dedupe_key=f"mo-done:{mo.id}")
    await check_achievements(session, await session.get(User, mo.seller_id))


async def _refund(session: AsyncSession, mo: MarketOrder, new_status: str) -> None:
    esc = await system_user(session, "escrow")
    k = f"mo:{mo.public_id}:refund"
    await ledger.post_entry(session, user_id=esc.id, currency=mo.currency, amount=-mo.amount, kind="market_refund", idem=k + ":out", ref_type="market_order", ref_id=mo.public_id)
    await ledger.post_entry(session, user_id=mo.buyer_id, currency=mo.currency, amount=mo.amount, kind="market_refund", idem=k + ":buyer", ref_type="market_order", ref_id=mo.public_id)
    li = await session.get(MarketListing, mo.listing_id, with_for_update=True)
    if li and li.status in ("active", "sold_out"):
        li.quantity += mo.qty
        li.status = "active"
    mo.status = new_status
    await notify(session, mo.buyer_id, "market", "↩️ Pul qaytarildi", f"{mo.amount} {mo.currency.replace('_', ' ')}", dedupe_key=f"mo-ref:{mo.id}")


async def deliver(session, user: User, oid: int) -> MarketOrder:
    mo = await _get_order(session, oid)
    if mo.seller_id != user.id:
        raise forbidden()
    if mo.status != "held":
        raise DomainError("bad_state", "Holat mos emas", 409)
    mo.status, mo.delivered_at = "delivered", utcnow()
    await notify(session, mo.buyer_id, "market", "📬 Sotuvchi topshirdi", "Qabul qilib, tasdiqlang.")
    return mo


async def confirm(session, user: User, oid: int) -> MarketOrder:
    mo = await _get_order(session, oid)
    if mo.buyer_id != user.id:
        raise forbidden()
    if mo.status not in ("held", "delivered"):
        raise DomainError("bad_state", "Holat mos emas", 409)
    await _release(session, mo)
    return mo


async def cancel(session, user: User, oid: int) -> MarketOrder:
    mo = await _get_order(session, oid)
    if user.id not in (mo.buyer_id, mo.seller_id):
        raise forbidden()
    if mo.status != "held" and not (mo.status == "delivered" and user.id == mo.seller_id):
        raise DomainError("bad_state", "Bekor qilib bo'lmaydi - nizo oching", 409)
    await _refund(session, mo, "cancelled")
    return mo


async def open_dispute(session, user: User, oid: int, reason: str) -> Dispute:
    mo = await _get_order(session, oid)
    if user.id not in (mo.buyer_id, mo.seller_id):
        raise forbidden()
    if mo.status not in ("held", "delivered"):
        raise DomainError("bad_state", "Nizo ochib bo'lmaydi", 409)
    mo.status = "disputed"
    d = Dispute(kind="dispute", ref_type="market_order", ref_id=mo.id, opened_by=user.id, reason=reason[:1000])
    session.add(d)
    await session.flush()
    return d


async def resolve_dispute(session, dispute_id: int, decision: str, admin_id: int, note: str | None, ip=None) -> Dispute:
    d = (await session.execute(select(Dispute).where(Dispute.id == dispute_id).with_for_update())).scalar_one_or_none()
    if not d:
        raise not_found()
    if d.status != "open":
        raise DomainError("already_processed", "Nizo allaqachon hal qilingan", 409)
    if d.ref_type == "market_order":
        mo = await _get_order(session, d.ref_id)
        if decision == "release_to_seller":
            await _release(session, mo)
        elif decision == "refund_buyer":
            await _refund(session, mo, "refunded")
        else:
            raise DomainError("bad_decision", "Qaror noto'g'ri")
    elif decision not in ("resolved", "rejected"):
        raise DomainError("bad_decision", "Qaror noto'g'ri")
    d.status, d.resolution, d.resolved_by, d.resolved_at = "resolved", (note or decision)[:500], admin_id, utcnow()
    await audit.log(session, admin_id, "dispute.resolve", d.ref_type, d.ref_id, {"decision": decision, "note": note}, ip)
    return d


async def send_message(session, user: User, oid: int, body: str) -> MarketMessage:
    mo = await session.get(MarketOrder, oid)
    if not mo or user.id not in (mo.buyer_id, mo.seller_id):
        raise not_found()
    body = (body or "").strip()
    if not body or len(body) > 1000:
        raise DomainError("bad_message", "Xabar bo'sh yoki juda uzun")
    m = MarketMessage(market_order_id=oid, sender_id=user.id, body=body)
    session.add(m)
    await session.flush()
    await notify(session, mo.seller_id if user.id == mo.buyer_id else mo.buyer_id, "market", "💬 Yangi xabar", body[:100])
    return m


async def review(session, user: User, oid: int, rating: int, text: str | None) -> Review:
    mo = await session.get(MarketOrder, oid)
    if not mo or mo.buyer_id != user.id:
        raise not_found()
    if mo.status != "completed":
        raise DomainError("bad_state", "Faqat yakunlangan buyurtmaga sharh yoziladi", 409)
    if not 1 <= rating <= 5:
        raise DomainError("bad_rating", "Reyting 1-5")
    if await session.scalar(select(Review.id).where(Review.market_order_id == oid)):
        raise DomainError("duplicate", "Sharh allaqachon yozilgan", 409)
    r = Review(author_id=user.id, target_user_id=mo.seller_id, market_order_id=oid, rating=rating, text=(text or "")[:500])
    session.add(r)
    await session.flush()
    avg, cnt = (await session.execute(select(func.avg(Review.rating), func.count(Review.id)).where(Review.target_user_id == mo.seller_id, Review.market_order_id.isnot(None)))).one()
    sp = await seller_profile(session, await session.get(User, mo.seller_id))
    sp.rating_avg, sp.rating_count = int(round(float(avg) * 100)), cnt
    return r
