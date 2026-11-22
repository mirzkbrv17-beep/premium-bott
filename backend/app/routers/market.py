from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..errors import DomainError, not_found
from ..models import Dispute, MarketListing, MarketMessage, MarketOrder, Review, SellerProfile, User, utcnow
from ..serializers import listing_dict
from ..services import market as svc

router = APIRouter(prefix="/api/market")


async def _seller(session, uid: int) -> dict:
    u = await session.get(User, uid)
    sp = await session.get(SellerProfile, uid)
    return {"abu_id": u.abu_id, "name": (sp.display_name if sp and sp.display_name else u.first_name) or u.abu_id, "verified": bool(sp and sp.verified),
            "rating": (sp.rating_avg / 100 if sp else 0), "rating_count": sp.rating_count if sp else 0, "sales": sp.sales_count if sp else 0}


class ListingIn(BaseModel):
    category: str
    title: str
    description: str | None = None
    price_amount: int
    price_currency: str
    quantity: int = 1


class ListingPatch(BaseModel):
    category: str | None = None
    title: str | None = None
    description: str | None = None
    price_amount: int | None = None
    price_currency: str | None = None
    quantity: int | None = None


@router.get("/categories")
async def cats(user: User = Depends(current_user)):
    return list(svc.CATEGORIES)


@router.get("/listings")
async def listings(category: str | None = None, q: str | None = None, sort: str = "new", currency: str | None = None, page: int = Query(1, ge=1),
                   size: int = Query(30, ge=1, le=60), user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    stmt = select(MarketListing).where(MarketListing.status == "active")
    if category:
        stmt = stmt.where(MarketListing.category == category)
    if currency:
        stmt = stmt.where(MarketListing.price_currency == currency)
    if q:
        stmt = stmt.where(MarketListing.title.ilike(f"%{q}%"))
    order = {"price_asc": [MarketListing.price_amount.asc()], "price_desc": [MarketListing.price_amount.desc()]}.get(sort, [MarketListing.id.desc()])
    # targ'ib qilinganlar tepada (faqat "new" saralashda)
    if sort == "new":
        order = [(MarketListing.promoted_until > utcnow()).desc().nulls_last(), MarketListing.id.desc()]
    rows = (await session.execute(stmt.order_by(*order).limit(size).offset((page - 1) * size))).scalars().all()
    return [listing_dict(li, await _seller(session, li.seller_id)) for li in rows]


@router.post("/listings")
async def create(body: ListingIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return listing_dict(await svc.create_listing(session, user, body.model_dump()))


@router.get("/listings/{lid}")
async def one(lid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    li = await session.get(MarketListing, lid)
    if not li or (li.status != "active" and li.seller_id != user.id):
        raise not_found()
    if li.seller_id != user.id:
        li.views += 1
    return listing_dict(li, await _seller(session, li.seller_id))


@router.patch("/listings/{lid}")
async def edit(lid: int, body: ListingPatch, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    li = await session.get(MarketListing, lid, with_for_update=True)
    if not li:
        raise not_found()
    return listing_dict(await svc.update_listing(session, user, li, body.model_dump(exclude_none=True)))


@router.post("/listings/{lid}/toggle")
async def toggle(lid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    li = await session.get(MarketListing, lid, with_for_update=True)
    if not li:
        raise not_found()
    return listing_dict(await svc.toggle_listing(li, user))


@router.post("/listings/{lid}/promote")
async def promote(lid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    li = await session.get(MarketListing, lid, with_for_update=True)
    if not li:
        raise not_found()
    return listing_dict(await svc.promote(session, user, li))


class BuyIn(BaseModel):
    qty: int = 1
    idempotency_key: str = Field(min_length=8, max_length=100)


def _mo(mo: MarketOrder, me: int) -> dict:
    return {"id": mo.id, "public_id": mo.public_id, "title": mo.title, "qty": mo.qty, "amount": mo.amount, "currency": mo.currency, "status": mo.status,
            "role": "buyer" if mo.buyer_id == me else "seller", "created_at": mo.created_at.isoformat(), "listing_id": mo.listing_id}


@router.post("/listings/{lid}/buy")
async def buy(lid: int, body: BuyIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    mo, _ = await svc.buy(session, user, lid, body.qty, body.idempotency_key)
    return _mo(mo, user.id)


@router.get("/my/listings")
async def my_listings(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(MarketListing).where(MarketListing.seller_id == user.id).order_by(MarketListing.id.desc()))).scalars()
    return [listing_dict(li) for li in rows]


@router.get("/my/orders")
async def my_orders(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(MarketOrder).where(or_(MarketOrder.buyer_id == user.id, MarketOrder.seller_id == user.id)).order_by(MarketOrder.id.desc()).limit(100))).scalars()
    return [_mo(m, user.id) for m in rows]


@router.get("/my/stats")
async def my_stats(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    sp = await svc.seller_profile(session, user)
    rows = (await session.execute(select(MarketListing).where(MarketListing.seller_id == user.id))).scalars().all()
    return {"seller": await _seller(session, user.id), "verification_status": sp.verification_status,
            "listings": len(rows), "views": sum(r.views for r in rows), "active": sum(1 for r in rows if r.status == "active")}


@router.post("/seller/apply")
async def apply_verification(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    sp = await svc.seller_profile(session, user)
    if sp.verified or sp.verification_status == "pending":
        raise DomainError("bad_state", "So'rov allaqachon yuborilgan yoki tasdiqlangan", 409)
    sp.verification_status = "pending"
    return {"verification_status": "pending"}


@router.get("/seller/{abu_id}")
async def seller_page(abu_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    u = (await session.execute(select(User).where(User.abu_id == abu_id.upper(), User.kind == "user"))).scalar_one_or_none()
    if not u:
        raise not_found()
    lis = (await session.execute(select(MarketListing).where(MarketListing.seller_id == u.id, MarketListing.status == "active").order_by(MarketListing.id.desc()).limit(50))).scalars()
    revs = (await session.execute(select(Review, User).join(User, User.id == Review.author_id).where(Review.target_user_id == u.id, Review.market_order_id.isnot(None)).order_by(Review.id.desc()).limit(20))).all()
    return {"seller": await _seller(session, u.id), "listings": [listing_dict(li) for li in lis],
            "reviews": [{"rating": r.rating, "text": r.text, "author": a.first_name or a.abu_id, "created_at": r.created_at.isoformat()} for r, a in revs]}


@router.post("/orders/{oid}/deliver")
async def deliver(oid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return _mo(await svc.deliver(session, user, oid), user.id)


@router.post("/orders/{oid}/confirm")
async def confirm(oid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return _mo(await svc.confirm(session, user, oid), user.id)


@router.post("/orders/{oid}/cancel")
async def cancel(oid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return _mo(await svc.cancel(session, user, oid), user.id)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/orders/{oid}/dispute")
async def dispute(oid: int, body: ReasonIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    d = await svc.open_dispute(session, user, oid, body.reason)
    return {"dispute_id": d.id, "status": d.status}


class MsgIn(BaseModel):
    body: str


@router.get("/orders/{oid}/messages")
async def messages(oid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    mo = await session.get(MarketOrder, oid)
    if not mo or user.id not in (mo.buyer_id, mo.seller_id):
        raise not_found()
    rows = (await session.execute(select(MarketMessage).where(MarketMessage.market_order_id == oid).order_by(MarketMessage.id))).scalars()
    return [{"mine": m.sender_id == user.id, "body": m.body, "created_at": m.created_at.isoformat()} for m in rows]


@router.post("/orders/{oid}/messages")
async def post_message(oid: int, body: MsgIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await svc.send_message(session, user, oid, body.body)
    return {"ok": True}


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str | None = Field(None, max_length=500)


@router.post("/orders/{oid}/review")
async def review(oid: int, body: ReviewIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    r = await svc.review(session, user, oid, body.rating, body.text)
    return {"id": r.id}


@router.post("/listings/{lid}/report")
async def report(lid: int, body: ReasonIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    li = await session.get(MarketListing, lid)
    if not li:
        raise not_found()
    session.add(Dispute(kind="report", ref_type="listing", ref_id=li.id, opened_by=user.id, reason=body.reason))
    return {"ok": True}
