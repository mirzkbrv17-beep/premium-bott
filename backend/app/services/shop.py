"""ABU SHOP buyurtmalari va ABU RENT ijaralari. To'lov = ichki balansdan ledger orqali (to'lovsiz hech narsa faol emas)."""
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError, forbidden, not_found
from ..models import (ABU_F, ABU_TON, CURRENCIES, InventoryItem, LedgerEntry, Order, OrderItem, Product, Rental,
                      RentalAvailability, User, utcnow)
from ..timeutil import ceil_div, now_utc, tashkent_date, tashkent_midnight_utc
from . import audit, ledger, settings_svc
from .notify import notify
from .progress import add_xp, check_achievements, vip_discount_percent

BUSY = ("reserved", "active", "expired", "disputed")  # 'expired' = qaytarilishi tasdiqlanmagan -> band


async def currency_rate(session: AsyncSession, currency: str) -> int:
    key = {ABU_F: "abu_f_uzs_per_unit", ABU_TON: "abu_ton_uzs_per_unit"}.get(currency)
    if not key:
        raise DomainError("bad_currency", "To'lov valyutasi noto'g'ri")
    v = await settings_svc.get(session, key, 250 if currency == ABU_TON else 10)
    return max(1, int(v))


def unit_price(p: Product) -> int:
    return p.price_uzs * (100 - p.discount_percent) // 100


async def stock_info(session: AsyncSession, p: Product) -> dict:
    if p.is_unique:
        n = await session.scalar(select(func.count(InventoryItem.id)).where(InventoryItem.product_id == p.id, InventoryItem.status == "available"))
        return {"available": n > 0, "count": n}
    if p.stock is None:
        return {"available": True, "count": None}
    return {"available": p.stock > 0, "count": p.stock}


async def _charge(session: AsyncSession, user: User, total_uzs: int, currency: str, kind: str, idem: str, ref: str, note: str):
    rate = await currency_rate(session, currency)
    amount = max(1, ceil_div(total_uzs, rate))
    entry, _ = await ledger.post_entry(session, user_id=user.id, currency=currency, amount=-amount, kind=kind, idem=idem,
                                       ref_type="order", ref_id=ref, note=note)
    return rate, amount, entry


async def _finalize_spend(session: AsyncSession, user: User, total_uzs: int) -> None:
    u = await session.get(User, user.id, with_for_update=True)
    u.spent_uzs_total += total_uzs
    await add_xp(session, u.id, max(1, total_uzs // 10_000), "order")
    await check_achievements(session, u)


async def place_order(session: AsyncSession, user: User, *, product_id: int, qty: int, pay_currency: str, idem: str,
                      inventory_item_id: int | None = None) -> tuple[Order, bool]:
    ex = (await session.execute(select(Order).where(Order.user_id == user.id, Order.idempotency_key == idem))).scalar_one_or_none()
    if ex:
        return ex, False
    if pay_currency not in CURRENCIES or qty < 1 or qty > 100:
        raise DomainError("bad_request", "So'rov noto'g'ri")
    p = (await session.execute(select(Product).where(Product.id == product_id).with_for_update(of=Product))).scalar_one_or_none()
    if not p or not p.active or p.deleted_at or not p.sale_enabled:
        raise DomainError("unavailable", "Mahsulot sotuvda emas", 404)
    if p.category.kind in ("abu_f", "abu_ton"):
        raise DomainError("use_topup", "ABU F / ABU TON balans to'ldirish orqali olinadi")
    item = None
    if p.is_unique:
        if not inventory_item_id or qty != 1:
            raise DomainError("bad_request", "Noyob buyum tanlanishi kerak")
        item = (await session.execute(select(InventoryItem).where(InventoryItem.id == inventory_item_id, InventoryItem.product_id == p.id)
                                      .with_for_update(of=InventoryItem))).scalar_one_or_none()
        if not item or item.status != "available":
            raise DomainError("unavailable", "Buyum mavjud emas", 409)
        busy = await session.scalar(select(func.count(Rental.id)).where(Rental.inventory_item_id == item.id, Rental.status.in_(BUSY)))
        if busy:
            raise DomainError("unavailable", "Buyum hozir ijarada", 409)
    elif p.stock is not None:
        if p.stock < qty:
            raise DomainError("out_of_stock", "Omborda yetarli emas", 409)
        p.stock -= qty
    base = unit_price(p) * qty
    vip = await vip_discount_percent(session, user)
    total = base - base * vip // 100
    title = item.name if item else p.title
    order = Order(user_id=user.id, kind="sale", status="paid", total_uzs=total, discount_uzs=p.price_uzs * qty - total,
                  pay_currency=pay_currency, pay_amount=0, rate_snapshot=1, idempotency_key=idem)
    session.add(order)
    await session.flush()
    rate, amount, entry = await _charge(session, user, total, pay_currency, "purchase", f"order:{user.id}:{idem}", order.public_id, title)
    order.rate_snapshot, order.pay_amount, order.ledger_tx_id = rate, amount, entry.tx_id
    session.add(OrderItem(order_id=order.id, product_id=p.id, inventory_item_id=item.id if item else None, qty=qty,
                          unit_price_uzs=total // qty, title=title))
    if item:
        item.status, item.owner_user_id = "sold", user.id
    await session.flush()
    await _finalize_spend(session, user, total)
    await notify(session, user.id, "order", "🛒 Buyurtma qabul qilindi", f"{title} - {order.public_id}")
    await session.refresh(order, ["items"])
    return order, True


# ------------------------------------------------------------------ ijara
async def rent_item(session: AsyncSession, user: User, *, inventory_item_id: int, start_date: date, days: int,
                    pay_currency: str, idem: str) -> tuple[Order, Rental, bool]:
    ex = (await session.execute(select(Order).where(Order.user_id == user.id, Order.idempotency_key == idem))).scalar_one_or_none()
    if ex:
        r = (await session.execute(select(Rental).where(Rental.order_id == ex.id))).scalar_one()
        return ex, r, False
    if pay_currency not in CURRENCIES:
        raise DomainError("bad_currency", "To'lov valyutasi noto'g'ri")
    # buyumni qulflaymiz: bir vaqtda ikki kishi ijaraga ololmaydi
    item = (await session.execute(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update(of=InventoryItem))).scalar_one_or_none()
    if not item:
        raise not_found("Buyum topilmadi")
    p = item.product
    if not p.active or p.deleted_at or not p.rent_enabled or item.status != "available":
        raise DomainError("unavailable", "Buyum ijaraga berilmaydi", 409)
    if days < p.rent_min_days or days > p.rent_max_days:
        raise DomainError("bad_days", f"Muddat {p.rent_min_days}-{p.rent_max_days} kun bo'lishi kerak")
    today = tashkent_date()
    if start_date < today or start_date > today + timedelta(days=90):
        raise DomainError("bad_date", "Boshlanish sanasi noto'g'ri")
    start_at = tashkent_midnight_utc(start_date)
    end_at = start_at + timedelta(days=days)
    clash = await session.scalar(select(func.count(Rental.id)).where(
        Rental.inventory_item_id == item.id, Rental.status.in_(BUSY),
        (Rental.status == "expired") | and_(Rental.start_at < end_at, Rental.end_at > start_at)))
    block = await session.scalar(select(func.count(RentalAvailability.id)).where(
        RentalAvailability.inventory_item_id == item.id, RentalAvailability.start_at < end_at, RentalAvailability.end_at > start_at))
    if clash or block:
        raise DomainError("busy", "Bu sanalarda buyum band", 409)
    ppd = item.rent_price_per_day or p.rent_price_per_day
    base = ppd * days
    vip = await vip_discount_percent(session, user)
    total = base - base * vip // 100
    order = Order(user_id=user.id, kind="rent", status="paid", total_uzs=total, discount_uzs=base - total,
                  pay_currency=pay_currency, pay_amount=0, rate_snapshot=1, idempotency_key=idem)
    session.add(order)
    await session.flush()
    rate, amount, entry = await _charge(session, user, total, pay_currency, "rental", f"order:{user.id}:{idem}", order.public_id, item.name)
    order.rate_snapshot, order.pay_amount, order.ledger_tx_id = rate, amount, entry.tx_id  # to'lov tasdiqlandi
    session.add(OrderItem(order_id=order.id, product_id=p.id, inventory_item_id=item.id, qty=1, unit_price_uzs=total, title=item.name))
    status = "active" if start_at <= now_utc() else "reserved"
    rental = Rental(user_id=user.id, inventory_item_id=item.id, product_id=p.id, order_id=order.id, start_at=start_at, end_at=end_at,
                    days=days, price_per_day_uzs=ppd, total_uzs=total, status=status)
    session.add(rental)
    await session.flush()
    await _finalize_spend(session, user, total)
    await notify(session, user.id, "rental", "🕒 Ijara rasmiylashtirildi", f"{item.name}: {start_date} dan {days} kun")
    await session.refresh(order, ["items"])
    await session.refresh(rental, ["item"])
    return order, rental, True


async def calendar(session: AsyncSession, item_id: int) -> list[dict]:
    now = now_utc()
    out = []
    rows = (await session.execute(select(Rental).where(Rental.inventory_item_id == item_id, Rental.status.in_(BUSY)))).scalars()
    for r in rows:
        out.append({"start": r.start_at.isoformat(), "end": (r.end_at if r.status != "expired" else now + timedelta(days=3650)).isoformat(), "type": "rented"})
    for b in (await session.execute(select(RentalAvailability).where(RentalAvailability.inventory_item_id == item_id, RentalAvailability.end_at > now))).scalars():
        out.append({"start": b.start_at.isoformat(), "end": b.end_at.isoformat(), "type": "blocked"})
    return sorted(out, key=lambda x: x["start"])


async def tick_rentals(session: AsyncSession) -> dict:
    """Scheduler: reserved->active, active->expired (qaytarildi DEB BELGILANMAYDI), eslatmalar."""
    now = now_utc()
    started = expired = reminded = 0
    hours = int(await settings_svc.get(session, "rental_remind_hours", 24))
    rows = (await session.execute(select(Rental).where(Rental.status.in_(["reserved", "active"])).with_for_update(skip_locked=True, of=Rental))).scalars().all()
    for r in rows:
        if r.status == "reserved" and r.start_at <= now:
            r.status = "active"; started += 1
        if r.status == "active" and r.end_at <= now:
            r.status = "expired"; expired += 1
            await notify(session, r.user_id, "rental", "⏰ Ijara muddati tugadi", "Buyumni qaytaring. Qaytarilishi admin tomonidan tasdiqlanadi.", dedupe_key=f"rent-exp:{r.id}")
        elif r.status == "active" and not r.remind_sent and r.end_at - now <= timedelta(hours=hours):
            r.remind_sent = True; reminded += 1
            await notify(session, r.user_id, "rental", "⏳ Ijara tugashiga oz qoldi", f"Tugash: {r.end_at.astimezone().strftime('%d.%m %H:%M')}", dedupe_key=f"rent-rem:{r.id}")
    await session.flush()
    return {"started": started, "expired": expired, "reminded": reminded}


# ------------------------------------------------------------------ admin: holat, qaytarish, refund
async def set_order_status(session: AsyncSession, order_id: int, status: str, admin_id: int, note: str | None = None, ip=None) -> Order:
    if status not in ("processing", "completed", "cancelled"):
        raise DomainError("bad_status", "Holat noto'g'ri")
    o = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one_or_none()
    if not o:
        raise not_found()
    if status == "cancelled":
        return await refund_order(session, o, admin_id, note, ip)
    if o.status in ("refunded", "cancelled"):
        raise DomainError("bad_state", "Bekor qilingan buyurtmani o'zgartirib bo'lmaydi", 409)
    o.status = status
    if note:
        o.delivery_note = note
    await audit.log(session, admin_id, f"order.{status}", "order", o.public_id, {"note": note}, ip)
    await notify(session, o.user_id, "order", f"📦 Buyurtma: {status}", note or o.public_id)
    return o


async def refund_order(session: AsyncSession, o: Order, admin_id: int, note: str | None = None, ip=None) -> Order:
    if o.status in ("refunded", "cancelled"):
        raise DomainError("already_processed", "Buyurtma allaqachon qaytarilgan", 409)
    entry = (await session.execute(select(LedgerEntry).where(LedgerEntry.tx_id == o.ledger_tx_id))).scalar_one()
    await ledger.reverse_entry(session, entry, idem=f"refund:{o.public_id}", kind="refund", note=note, admin_id=admin_id)
    for it in o.items:
        if it.inventory_item_id:
            inv = await session.get(InventoryItem, it.inventory_item_id, with_for_update={"of": InventoryItem})
            if o.kind == "sale":
                inv.status, inv.owner_user_id = "available", None
        elif o.kind == "sale":
            p = await session.get(Product, it.product_id, with_for_update={"of": Product})
            if p.stock is not None:
                p.stock += it.qty
    if o.kind == "rent":
        for r in (await session.execute(select(Rental).where(Rental.order_id == o.id))).scalars():
            r.status = "cancelled"
    u = await session.get(User, o.user_id, with_for_update=True)
    u.spent_uzs_total = max(0, u.spent_uzs_total - o.total_uzs)
    o.status = "refunded"
    await audit.log(session, admin_id, "order.refund", "order", o.public_id, {"note": note, "amount": o.pay_amount, "currency": o.pay_currency}, ip)
    await notify(session, o.user_id, "order", "↩️ Buyurtma qaytarildi", f"{o.pay_amount} {o.pay_currency.replace('_', ' ')} balansga qaytarildi")
    return o


async def mark_returned(session: AsyncSession, rental_id: int, admin_id: int, ip=None) -> Rental:
    r = (await session.execute(select(Rental).where(Rental.id == rental_id).with_for_update(of=Rental))).scalar_one_or_none()
    if not r:
        raise not_found()
    if r.status not in ("active", "expired", "disputed"):
        raise DomainError("bad_state", "Bu ijarani qaytarilgan deb belgilab bo'lmaydi", 409)
    r.status, r.returned_at = "returned", utcnow()
    await audit.log(session, admin_id, "rental.returned", "rental", r.public_id, {}, ip)
    await notify(session, r.user_id, "rental", "✅ Qaytarish tasdiqlandi", r.item.name)
    return r
