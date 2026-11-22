"""Admin API. Har endpoint serverda require_perm bilan himoyalangan; muhim amallar audit log'ga yoziladi."""
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import PERMISSIONS, AdminCtx, require_perm
from ..errors import DomainError, forbidden, not_found
from ..models import (Achievement, AdminUser, AppSetting, AuditLog, Category, Dispute, GiftTransfer, InventoryItem, LedgerEntry,
                      MandatoryChannel, MarketListing, MarketOrder, News, Order, PaymentProvider, Product, ProductMedia, PromoCode,
                      Question, Rental, RentalAvailability, Role, SellerProfile, SupportMessage, SupportTicket, Task, TonPackage,
                      TopUp, User, VIPTier, utcnow, ABU_F, ABU_TON, CURRENCIES, rand_id)
from ..serializers import order_dict, rental_dict, row, topup_dict
from ..services import audit, bonus, ledger, market as market_svc, settings_svc, shop as shop_svc, social, topup as topup_svc
from ..services.notify import notify
from ..timeutil import now_utc
from ..uploads import sniff_image

router = APIRouter(prefix="/api/admin")


def _dt(v):
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise DomainError("bad_date", "Sana formati noto'g'ri")
    return v


def crud(path: str, Model, perm: str, fields: list[str], *, order=None, soft_delete: str | None = None, validate=None, filters: list[str] = (), no_create=False, no_delete=False):
    """Oddiy jadvallar uchun list/create/patch/delete (audit bilan)."""
    name = Model.__tablename__

    def clean(d: dict) -> dict:
        out = {k: d[k] for k in fields if k in d}
        for k, v in list(out.items()):
            if k.endswith("_at"):
                out[k] = _dt(v)
        return out

    @router.get(f"/{path}")
    async def _list(request: Request, ctx: AdminCtx = Depends(require_perm(perm)), session: AsyncSession = Depends(get_session)):
        q = select(Model)
        if soft_delete:
            q = q.where(getattr(Model, soft_delete).is_(None))
        for f in filters:
            if f in request.query_params:
                q = q.where(getattr(Model, f) == request.query_params[f])
        q = q.order_by(order if order is not None else Model.id.desc() if hasattr(Model, "id") else None)
        return [row(o) for o in (await session.execute(q.limit(500))).scalars().unique()]

    if not no_create:
        @router.post(f"/{path}")
        async def _create(body: dict[str, Any], ctx: AdminCtx = Depends(require_perm(perm)), session: AsyncSession = Depends(get_session)):
            d = clean(body)
            if validate:
                validate(d)
            obj = Model(**d)
            session.add(obj)
            await session.flush()
            await audit.log(session, ctx.user.id, f"{name}.create", name, getattr(obj, "id", None), d, ctx.ip)
            return row(obj)

    @router.patch(f"/{path}/{{oid}}")
    async def _patch(oid: int, body: dict[str, Any], ctx: AdminCtx = Depends(require_perm(perm)), session: AsyncSession = Depends(get_session)):
        obj = await session.get(Model, oid)
        if obj is None:
            raise not_found()
        d = clean(body)
        if validate:
            validate({**row(obj), **d})
        for k, v in d.items():
            setattr(obj, k, v)
        await session.flush()
        await audit.log(session, ctx.user.id, f"{name}.update", name, oid, d, ctx.ip)
        return row(obj)

    if not no_delete:
        @router.delete(f"/{path}/{{oid}}")
        async def _delete(oid: int, ctx: AdminCtx = Depends(require_perm(perm)), session: AsyncSession = Depends(get_session)):
            obj = await session.get(Model, oid)
            if obj is None:
                raise not_found()
            if soft_delete:
                setattr(obj, soft_delete, utcnow())
                if hasattr(obj, "active"):
                    obj.active = False
            else:
                await session.delete(obj)
            await audit.log(session, ctx.user.id, f"{name}.delete", name, oid, {}, ctx.ip)
            return {"ok": True}


def _check_product(d: dict) -> None:
    if int(d.get("price_uzs", 0) or 0) < 0 or not 0 <= int(d.get("discount_percent", 0) or 0) <= 90:
        raise DomainError("bad_request", "Narx yoki chegirma noto'g'ri")
    if d.get("rent_enabled") and (int(d.get("rent_price_per_day", 0) or 0) <= 0 or int(d.get("rent_min_days", 1)) > int(d.get("rent_max_days", 30))):
        raise DomainError("bad_request", "Ijara narxi/muddati noto'g'ri")


crud("categories", Category, "products.manage", ["slug", "kind", "name", "icon", "sort", "active"], order=Category.sort)
crud("products", Product, "products.manage", ["category_id", "title", "subtitle", "description", "price_uzs", "discount_percent", "sale_enabled", "rent_enabled",
                                               "rent_price_per_day", "rent_min_days", "rent_max_days", "stock", "is_unique", "color", "meta", "active", "sort"],
     soft_delete="deleted_at", validate=_check_product, filters=["category_id"])
crud("inventory", InventoryItem, "products.manage", ["product_id", "item_ref", "name", "attrs", "color", "status", "rent_price_per_day"], filters=["product_id"])
crud("rental-blocks", RentalAvailability, "rentals.manage", ["inventory_item_id", "start_at", "end_at", "reason"], filters=["inventory_item_id"])
crud("ton-packages", TonPackage, "rates.manage", ["units", "price_uzs", "active", "sort"], order=TonPackage.sort)
crud("promo", PromoCode, "promo.manage", ["code", "mode", "currency", "amount", "max_uses", "expires_at", "active"], soft_delete="deleted_at", validate=bonus.validate_promo_payload)
crud("channels", MandatoryChannel, "channels.manage", ["chat_id", "title", "invite_url", "active", "sort"], order=MandatoryChannel.sort)
crud("vip-tiers", VIPTier, "vip.manage", ["name", "rank", "min_spent_uzs", "discount_percent", "badge", "perks", "active"], order=VIPTier.rank)
crud("achievements", Achievement, "settings.manage", ["code", "title", "description", "icon", "metric", "threshold", "xp_reward", "active"])
crud("tasks", Task, "content.manage", ["code", "title", "kind", "param", "currency", "amount", "xp", "active"])
crud("news", News, "content.manage", ["title", "body", "published"])
crud("questions", Question, "content.manage", ["text", "options", "correct_index", "active"])
crud("providers", PaymentProvider, "settings.manage", ["enabled", "sort"], no_create=True, no_delete=True, order=PaymentProvider.sort)


# ------------------------------------------------------------------ media
@router.post("/media")
async def upload_media(product_id: int = Form(...), inventory_item_id: int | None = Form(None), file: UploadFile = File(...),
                       ctx: AdminCtx = Depends(require_perm("products.manage")), session: AsyncSession = Depends(get_session)):
    if await session.get(Product, product_id) is None:
        raise not_found("Mahsulot topilmadi")
    data = await file.read(settings.max_upload_bytes + 1)
    kind, mime = sniff_image(data, settings.max_upload_bytes)
    m = ProductMedia(product_id=product_id, inventory_item_id=inventory_item_id, kind=kind, mime=mime, data=data, size=len(data))
    session.add(m)
    await session.flush()
    await audit.log(session, ctx.user.id, "media.upload", "product", product_id, {"kind": kind, "size": len(data)}, ctx.ip)
    return {"id": m.id, "kind": kind, "url": f"/api/media/{m.id}"}


@router.get("/media")
async def list_media(product_id: int, ctx: AdminCtx = Depends(require_perm("products.manage")), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(ProductMedia.id, ProductMedia.kind, ProductMedia.size, ProductMedia.inventory_item_id).where(ProductMedia.product_id == product_id))).all()
    return [{"id": i, "kind": k, "size": s, "inventory_item_id": ii, "url": f"/api/media/{i}"} for i, k, s, ii in rows]


@router.delete("/media/{mid}")
async def delete_media(mid: int, ctx: AdminCtx = Depends(require_perm("products.manage")), session: AsyncSession = Depends(get_session)):
    m = await session.get(ProductMedia, mid)
    if not m:
        raise not_found()
    await session.delete(m)
    await audit.log(session, ctx.user.id, "media.delete", "media", mid, {}, ctx.ip)
    return {"ok": True}


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
async def dashboard(period: str = Query("week", pattern="^(day|week|month)$"), ctx: AdminCtx = Depends(require_perm("dashboard.view")), session: AsyncSession = Depends(get_session)):
    since = now_utc() - timedelta(days={"day": 1, "week": 7, "month": 30}[period])
    c = lambda q: session.scalar(q)
    from ..models import OrderItem
    sold = (await session.execute(select(OrderItem.title, func.sum(OrderItem.qty).label("n")).join(Order, Order.id == OrderItem.order_id)
                                  .where(Order.kind == "sale", Order.status.notin_(["refunded", "cancelled"]), Order.created_at >= since).group_by(OrderItem.title).order_by(func.sum(OrderItem.qty).desc()).limit(5))).all()
    rented = (await session.execute(select(OrderItem.title, func.count(OrderItem.id).label("n")).join(Order, Order.id == OrderItem.order_id)
                                    .where(Order.kind == "rent", Order.status.notin_(["refunded", "cancelled"]), Order.created_at >= since).group_by(OrderItem.title).order_by(func.count(OrderItem.id).desc()).limit(5))).all()
    out = {"period": period,
           "users": {"total": await c(select(func.count(User.id)).where(User.kind == "user")), "new": await c(select(func.count(User.id)).where(User.kind == "user", User.created_at >= since))},
           "sales": {"orders": await c(select(func.count(Order.id)).where(Order.kind == "sale", Order.status.notin_(["refunded", "cancelled"]), Order.created_at >= since)),
                     "uzs": int(await c(select(func.coalesce(func.sum(Order.total_uzs), 0)).where(Order.kind == "sale", Order.status.notin_(["refunded", "cancelled"]), Order.created_at >= since)))},
           "rentals": {"active": await c(select(func.count(Rental.id)).where(Rental.status.in_(["active", "reserved"]))), "pending_return": await c(select(func.count(Rental.id)).where(Rental.status == "expired")),
                       "uzs": int(await c(select(func.coalesce(func.sum(Order.total_uzs), 0)).where(Order.kind == "rent", Order.status.notin_(["refunded", "cancelled"]), Order.created_at >= since)))},
           "payments": {"success_uzs": int(await c(select(func.coalesce(func.sum(TopUp.uzs_amount), 0)).where(TopUp.status == "success", TopUp.created_at >= since))),
                        "pending": await c(select(func.count(TopUp.id)).where(TopUp.status.in_(["pending", "awaiting_review"]))),
                        "awaiting_review": await c(select(func.count(TopUp.id)).where(TopUp.status == "awaiting_review"))},
           "open": {"disputes": await c(select(func.count(Dispute.id)).where(Dispute.status == "open")), "tickets": await c(select(func.count(SupportTicket.id)).where(SupportTicket.status == "open")),
                    "listings_pending": await c(select(func.count(MarketListing.id)).where(MarketListing.status == "pending")), "gifts_pending": await c(select(func.count(GiftTransfer.id)).where(GiftTransfer.status == "pending_review"))},
           "top_sold": [{"title": t, "n": int(n)} for t, n in sold], "top_rented": [{"title": t, "n": int(n)} for t, n in rented]}
    return out


# ------------------------------------------------------------------ sozlamalar / kurslar
@router.get("/settings")
async def get_settings(ctx: AdminCtx = Depends(require_perm("settings.manage")), session: AsyncSession = Depends(get_session)):
    d = await settings_svc.all_settings(session)
    d.setdefault("abu_ton_uzs_per_unit", 250)
    return d


class SettingIn(BaseModel):
    value: Any


INT_KEYS = {"abu_f_uzs_per_unit", "abu_f_min_units", "abu_ton_uzs_per_unit", "uzs_per_star", "referral_reward_f", "referral_reward_ton", "referral_wait_minutes", "referral_daily_cap",
            "gift_min_account_age_hours", "market_commission_percent", "market_max_active_listings", "rental_remind_hours", "daily_question_xp", "xp_per_level"}


@router.put("/settings/{key}")
async def put_setting(key: str, body: SettingIn, ctx: AdminCtx = Depends(require_perm("settings.manage")), session: AsyncSession = Depends(get_session)):
    if key not in settings_svc.DEFAULTS and key != "abu_ton_uzs_per_unit":
        raise DomainError("bad_key", "Noma'lum sozlama")
    if key in ("abu_f_uzs_per_unit", "abu_ton_uzs_per_unit", "uzs_per_star") and not ctx.can("rates.manage"):
        raise forbidden("Kurslarni o'zgartirish uchun rates.manage kerak")
    v = body.value
    if key in INT_KEYS:
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or (key.endswith("_per_unit") or key == "uzs_per_star") and v < 1:
            raise DomainError("bad_value", "Qiymat musbat butun son bo'lishi kerak")
    old = await settings_svc.get(session, key)
    await settings_svc.put(session, key, v)
    await audit.log(session, ctx.user.id, "setting.update", "setting", key, {"old": old, "new": v}, ctx.ip)  # eski tranzaksiyalar eski kurs bilan qoladi (snapshot)
    return {"key": key, "value": v}


# ------------------------------------------------------------------ to'lovlar
@router.get("/topups")
async def list_topups(status: str | None = None, q: str | None = None, ctx: AdminCtx = Depends(require_perm("payments.view")), session: AsyncSession = Depends(get_session)):
    stmt = select(TopUp, User).join(User, User.id == TopUp.user_id)
    if status:
        stmt = stmt.where(TopUp.status == status)
    if q:
        stmt = stmt.where(or_(TopUp.public_id.ilike(f"%{q}%"), User.abu_id.ilike(f"%{q}%")))
    return [topup_dict(t) | {"user": u.abu_id, "user_name": u.first_name, "internal_id": t.id} for t, u in (await session.execute(stmt.order_by(TopUp.id.desc()).limit(200))).all()]


@router.get("/topups/{tid}/receipt")
async def topup_receipt(tid: int, ctx: AdminCtx = Depends(require_perm("payments.view")), session: AsyncSession = Depends(get_session)):
    t = await session.get(TopUp, tid)
    if not t or not t.receipt_data:
        raise not_found()
    return Response(t.receipt_data, media_type=t.receipt_mime, headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"})


class ReviewIn(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=300)


@router.post("/topups/{tid}/review")
async def review_topup(tid: int, body: ReviewIn, ctx: AdminCtx = Depends(require_perm("payments.review")), session: AsyncSession = Depends(get_session)):
    t = await topup_svc.admin_review(session, tid, approve=body.approve, admin_id=ctx.user.id, note=body.note, ip=ctx.ip)
    return topup_dict(t)


# ------------------------------------------------------------------ buyurtma / ijara
@router.get("/orders")
async def list_orders(status: str | None = None, kind: str | None = None, ctx: AdminCtx = Depends(require_perm("orders.view")), session: AsyncSession = Depends(get_session)):
    stmt = select(Order, User).join(User, User.id == Order.user_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if kind:
        stmt = stmt.where(Order.kind == kind)
    return [order_dict(o) | {"user": u.abu_id, "user_name": u.first_name} for o, u in (await session.execute(stmt.order_by(Order.id.desc()).limit(200))).all()]


class OrderStatusIn(BaseModel):
    status: str
    note: str | None = Field(None, max_length=500)


@router.post("/orders/{oid}/status")
async def order_status(oid: int, body: OrderStatusIn, ctx: AdminCtx = Depends(require_perm("orders.manage")), session: AsyncSession = Depends(get_session)):
    return order_dict(await shop_svc.set_order_status(session, oid, body.status, ctx.user.id, body.note, ctx.ip))


@router.get("/rentals")
async def list_rentals(status: str | None = None, ctx: AdminCtx = Depends(require_perm("orders.view")), session: AsyncSession = Depends(get_session)):
    stmt = select(Rental, User).join(User, User.id == Rental.user_id)
    if status:
        stmt = stmt.where(Rental.status == status)
    return [rental_dict(r) | {"user": u.abu_id} for r, u in (await session.execute(stmt.order_by(Rental.id.desc()).limit(200))).unique().all()]


@router.post("/rentals/{rid}/returned")
async def rental_returned(rid: int, ctx: AdminCtx = Depends(require_perm("rentals.manage")), session: AsyncSession = Depends(get_session)):
    return rental_dict(await shop_svc.mark_returned(session, rid, ctx.user.id, ctx.ip))


# ------------------------------------------------------------------ foydalanuvchilar
def _user_row(u: User) -> dict:
    return {"id": u.id, "abu_id": u.abu_id, "name": u.first_name, "username": u.username, "is_banned": u.is_banned, "ban_reason": u.ban_reason, "xp": u.xp,
            "spent_uzs_total": u.spent_uzs_total, "created_at": u.created_at.isoformat()}


@router.get("/users")
async def list_users(q: str | None = None, ctx: AdminCtx = Depends(require_perm("users.view")), session: AsyncSession = Depends(get_session)):
    stmt = select(User).where(User.kind == "user")
    if q:
        like = f"%{q}%"
        cond = [User.abu_id.ilike(like), User.username.ilike(like), User.first_name.ilike(like)]
        if q.isdigit():
            cond.append(User.telegram_id == int(q))  # Telegram ID faqat adminga qidiruv uchun
        stmt = stmt.where(or_(*cond))
    return [_user_row(u) for u in (await session.execute(stmt.order_by(User.id.desc()).limit(100))).scalars()]


@router.get("/users/{abu_id}")
async def user_detail(abu_id: str, ctx: AdminCtx = Depends(require_perm("users.view")), session: AsyncSession = Depends(get_session)):
    u = (await session.execute(select(User).where(User.abu_id == abu_id.upper(), User.kind == "user"))).scalar_one_or_none()
    if not u:
        raise not_found()
    ents = (await session.execute(select(LedgerEntry).where(LedgerEntry.user_id == u.id).order_by(LedgerEntry.id.desc()).limit(30))).scalars()
    return _user_row(u) | {"balances": await ledger.balances(session, u.id),
                           "ledger": [{"tx_id": e.tx_id, "kind": e.kind, "amount": e.amount, "currency": e.currency, "note": e.note, "created_at": e.created_at.isoformat()} for e in ents]}


class BanIn(BaseModel):
    banned: bool
    reason: str | None = Field(None, max_length=300)


@router.post("/users/{abu_id}/ban")
async def ban_user(abu_id: str, body: BanIn, ctx: AdminCtx = Depends(require_perm("users.manage")), session: AsyncSession = Depends(get_session)):
    u = (await session.execute(select(User).where(User.abu_id == abu_id.upper(), User.kind == "user"))).scalar_one_or_none()
    if not u:
        raise not_found()
    if u.id == ctx.user.id:
        raise DomainError("self_ban", "O'zingizni cheklay olmaysiz")
    u.is_banned, u.ban_reason = body.banned, body.reason if body.banned else None
    await audit.log(session, ctx.user.id, "user.ban" if body.banned else "user.unban", "user", u.abu_id, {"reason": body.reason}, ctx.ip)
    return _user_row(u)


class AdjustIn(BaseModel):
    currency: str
    amount: int  # ishorali
    reason: str = Field(min_length=5, max_length=300)
    idempotency_key: str = Field(min_length=8, max_length=100)


@router.post("/users/{abu_id}/adjust")
async def adjust(abu_id: str, body: AdjustIn, ctx: AdminCtx = Depends(require_perm("balance.adjust")), session: AsyncSession = Depends(get_session)):
    u = (await session.execute(select(User).where(User.abu_id == abu_id.upper(), User.kind == "user"))).scalar_one_or_none()
    if not u:
        raise not_found()
    e, created = await ledger.post_entry(session, user_id=u.id, currency=body.currency, amount=body.amount, kind="admin_adjust", idem=f"adjust:{body.idempotency_key}",
                                         note=body.reason, admin_id=ctx.user.id, ref_type="admin", ref_id=str(ctx.user.id))
    if created:
        await audit.log(session, ctx.user.id, "balance.adjust", "user", u.abu_id, {"currency": body.currency, "amount": body.amount, "reason": body.reason, "tx": e.tx_id}, ctx.ip)
        await notify(session, u.id, "payment", "⚖️ Balans tuzatildi", f"{body.amount:+d} {body.currency.replace('_', ' ')}")
    return {"tx_id": e.tx_id, "balance_after": e.balance_after}


# ------------------------------------------------------------------ market moderatsiyasi / nizolar / sovg'alar
@router.get("/listings")
async def admin_listings(status: str | None = "pending", ctx: AdminCtx = Depends(require_perm("market.moderate")), session: AsyncSession = Depends(get_session)):
    stmt = select(MarketListing)
    if status:
        stmt = stmt.where(MarketListing.status == status)
    return [row(li) for li in (await session.execute(stmt.order_by(MarketListing.id.desc()).limit(200))).scalars()]


class ModIn(BaseModel):
    status: str = Field(pattern="^(active|rejected|removed|hidden)$")
    note: str | None = Field(None, max_length=300)


@router.post("/listings/{lid}/moderate")
async def moderate(lid: int, body: ModIn, ctx: AdminCtx = Depends(require_perm("market.moderate")), session: AsyncSession = Depends(get_session)):
    li = await session.get(MarketListing, lid, with_for_update=True)
    if not li:
        raise not_found()
    li.status, li.moderation_note = body.status, body.note
    await audit.log(session, ctx.user.id, "listing.moderate", "listing", li.public_id, body.model_dump(), ctx.ip)
    await notify(session, li.seller_id, "market", f"E'lon: {body.status}", f"{li.title}. {body.note or ''}")
    return row(li)


@router.get("/sellers")
async def sellers(status: str = "pending", ctx: AdminCtx = Depends(require_perm("market.moderate")), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(SellerProfile, User).join(User, User.id == SellerProfile.user_id).where(SellerProfile.verification_status == status))).all()
    return [{"user_id": s.user_id, "abu_id": u.abu_id, "name": s.display_name, "status": s.verification_status, "verified": s.verified, "banned": s.banned, "sales": s.sales_count} for s, u in rows]


class SellerIn(BaseModel):
    verified: bool | None = None
    banned: bool | None = None


@router.post("/sellers/{user_id}")
async def seller_update(user_id: int, body: SellerIn, ctx: AdminCtx = Depends(require_perm("market.moderate")), session: AsyncSession = Depends(get_session)):
    sp = await session.get(SellerProfile, user_id)
    if not sp:
        raise not_found()
    if body.verified is not None:
        sp.verified, sp.verification_status = body.verified, "verified" if body.verified else "rejected"
    if body.banned is not None:
        sp.banned = body.banned
    await audit.log(session, ctx.user.id, "seller.update", "seller", user_id, body.model_dump(exclude_none=True), ctx.ip)
    return {"ok": True}


@router.get("/disputes")
async def disputes(status: str | None = "open", ctx: AdminCtx = Depends(require_perm("disputes.manage")), session: AsyncSession = Depends(get_session)):
    stmt = select(Dispute)
    if status:
        stmt = stmt.where(Dispute.status == status)
    out = []
    for d in (await session.execute(stmt.order_by(Dispute.id.desc()).limit(200))).scalars():
        info = {}
        if d.ref_type == "market_order":
            mo = await session.get(MarketOrder, d.ref_id)
            info = {"title": mo.title, "amount": mo.amount, "currency": mo.currency, "order_status": mo.status}
        out.append(row(d) | info)
    return out


class ResolveIn(BaseModel):
    decision: str
    note: str | None = Field(None, max_length=500)


@router.post("/disputes/{did}/resolve")
async def resolve(did: int, body: ResolveIn, ctx: AdminCtx = Depends(require_perm("disputes.manage")), session: AsyncSession = Depends(get_session)):
    return row(await market_svc.resolve_dispute(session, did, body.decision, ctx.user.id, body.note, ctx.ip))


@router.get("/gifts")
async def admin_gifts(status: str = "pending_review", ctx: AdminCtx = Depends(require_perm("gifts.review")), session: AsyncSession = Depends(get_session)):
    return [row(g) for g in (await session.execute(select(GiftTransfer).where(GiftTransfer.status == status).order_by(GiftTransfer.id.desc()).limit(100))).scalars()]


class ApproveIn(BaseModel):
    approve: bool


@router.post("/gifts/{gid}/review")
async def gift_review(gid: int, body: ApproveIn, ctx: AdminCtx = Depends(require_perm("gifts.review")), session: AsyncSession = Depends(get_session)):
    return row(await social.review_gift(session, gid, body.approve, ctx.user.id, ctx.ip))


# ------------------------------------------------------------------ support
@router.get("/tickets")
async def admin_tickets(status: str | None = None, ctx: AdminCtx = Depends(require_perm("support.manage")), session: AsyncSession = Depends(get_session)):
    stmt = select(SupportTicket, User).join(User, User.id == SupportTicket.user_id)
    if status:
        stmt = stmt.where(SupportTicket.status == status)
    return [{"id": t.id, "subject": t.subject, "status": t.status, "user": u.abu_id, "updated_at": t.updated_at.isoformat()} for t, u in (await session.execute(stmt.order_by(SupportTicket.updated_at.desc()).limit(200))).all()]


@router.get("/tickets/{tid}")
async def admin_ticket(tid: int, ctx: AdminCtx = Depends(require_perm("support.manage")), session: AsyncSession = Depends(get_session)):
    t = await session.get(SupportTicket, tid)
    if not t:
        raise not_found()
    msgs = (await session.execute(select(SupportMessage).where(SupportMessage.ticket_id == tid).order_by(SupportMessage.id))).scalars()
    return {"id": t.id, "subject": t.subject, "status": t.status, "messages": [{"staff": m.is_staff, "body": m.body, "created_at": m.created_at.isoformat()} for m in msgs]}


class ReplyIn(BaseModel):
    body: str
    close: bool = False


@router.post("/tickets/{tid}/reply")
async def admin_reply(tid: int, body: ReplyIn, ctx: AdminCtx = Depends(require_perm("support.manage")), session: AsyncSession = Depends(get_session)):
    t = await session.get(SupportTicket, tid)
    if not t:
        raise not_found()
    await social.ticket_reply(session, t, ctx.user, body.body, staff=True)
    if body.close:
        t.status = "closed"
    await audit.log(session, ctx.user.id, "ticket.reply", "ticket", tid, {"close": body.close}, ctx.ip)
    return {"ok": True}


# ------------------------------------------------------------------ rollar, audit
@router.get("/roles")
async def roles(ctx: AdminCtx = Depends(require_perm("roles.manage")), session: AsyncSession = Depends(get_session)):
    rs = (await session.execute(select(Role).order_by(Role.id))).scalars().all()
    admins = (await session.execute(select(AdminUser, User).join(User, User.id == AdminUser.user_id))).all()
    return {"roles": [r.name for r in rs], "permissions": PERMISSIONS,
            "admins": [{"id": a.id, "abu_id": u.abu_id, "name": u.first_name, "role": a.role.name, "active": a.active} for a, u in admins]}


class AdminSetIn(BaseModel):
    abu_id: str
    role: str | None = None  # None = olib tashlash


@router.post("/admins")
async def set_admin(body: AdminSetIn, ctx: AdminCtx = Depends(require_perm("roles.manage")), session: AsyncSession = Depends(get_session)):
    u = (await session.execute(select(User).where(User.abu_id == body.abu_id.upper(), User.kind == "user"))).scalar_one_or_none()
    if not u:
        raise not_found("Foydalanuvchi topilmadi")
    ex = (await session.execute(select(AdminUser).where(AdminUser.user_id == u.id))).scalar_one_or_none()
    if body.role is None:
        if ex:
            if u.id == ctx.user.id:
                raise DomainError("self_demote", "O'zingizni olib tashlay olmaysiz")
            ex.active = False
    else:
        role = (await session.execute(select(Role).where(Role.name == body.role))).scalar_one_or_none()
        if not role:
            raise DomainError("bad_role", "Rol topilmadi")
        if ex:
            ex.role_id, ex.active = role.id, True
        else:
            session.add(AdminUser(user_id=u.id, role_id=role.id))
    await audit.log(session, ctx.user.id, "admin.set", "user", u.abu_id, {"role": body.role}, ctx.ip)
    return {"ok": True}


@router.get("/audit")
async def audit_list(action: str | None = None, ctx: AdminCtx = Depends(require_perm("audit.view")), session: AsyncSession = Depends(get_session)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    return [row(a) for a in (await session.execute(stmt.order_by(AuditLog.id.desc()).limit(200))).scalars()]
