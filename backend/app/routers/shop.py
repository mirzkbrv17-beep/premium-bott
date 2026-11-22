from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..errors import DomainError, not_found
from ..models import Category, Dispute, InventoryItem, Order, Product, ProductMedia, Rental, Review, User
from ..serializers import item_card, media_map, order_dict, product_card, rental_dict
from ..services import shop as svc

router = APIRouter(prefix="/api")


@router.get("/media/{mid}")
async def media(mid: int, session: AsyncSession = Depends(get_session)):
    from sqlalchemy.orm import undefer
    m = (await session.execute(select(ProductMedia).options(undefer(ProductMedia.data)).where(ProductMedia.id == mid))).scalar_one_or_none()
    if not m:
        raise not_found()
    return Response(m.data, media_type=m.mime, headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff",
                                                        "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.get("/shop/categories")
async def categories(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Category).where(Category.active.is_(True)).order_by(Category.sort, Category.id))).scalars()
    return [{"id": c.id, "slug": c.slug, "kind": c.kind, "name": c.name, "icon": c.icon} for c in rows]


def _sort(q, sort, price_col):
    return q.order_by(price_col.asc() if sort == "price_asc" else price_col.desc()) if sort in ("price_asc", "price_desc") else q


@router.get("/shop/products")
async def products(category: str | None = None, q: str | None = None, sort: str = "new", page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=60),
                   user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    stmt = select(Product).join(Category, Category.id == Product.category_id).where(
        Product.active.is_(True), Product.deleted_at.is_(None), Product.is_unique.is_(False), Product.sale_enabled.is_(True), Category.active.is_(True), Category.kind != "nft")
    if category:
        stmt = stmt.where(Category.slug == category)
    if q:
        stmt = stmt.where(or_(Product.title.ilike(f"%{q}%"), Product.public_id.ilike(f"%{q}%")))
    stmt = _sort(stmt, sort, Product.price_uzs).order_by(Product.sort, Product.id.desc()).limit(size).offset((page - 1) * size)
    prods = (await session.execute(stmt)).scalars().unique().all()
    mm = await media_map(session, [p.id for p in prods])
    return [await product_card(session, p, mm) for p in prods]


@router.get("/shop/nft")
async def nft_items(q: str | None = None, sort: str = "new", page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=60),
                    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    stmt = select(InventoryItem).join(Product, Product.id == InventoryItem.product_id).where(
        InventoryItem.status == "available", Product.active.is_(True), Product.deleted_at.is_(None), Product.sale_enabled.is_(True), Product.is_unique.is_(True))
    if q:
        stmt = stmt.where(or_(InventoryItem.name.ilike(f"%{q}%"), InventoryItem.item_ref.ilike(f"%{q}%")))
    stmt = _sort(stmt, sort, Product.price_uzs).order_by(InventoryItem.id.desc()).limit(size).offset((page - 1) * size)
    items = (await session.execute(stmt)).scalars().unique().all()
    mm = await media_map(session, list({i.product_id for i in items}))
    return [item_card(i, mm) for i in items]


class OrderIn(BaseModel):
    product_id: int
    qty: int = 1
    pay_currency: str
    idempotency_key: str = Field(min_length=8, max_length=100)
    inventory_item_id: int | None = None


@router.post("/shop/orders")
async def create_order(body: OrderIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    o, _ = await svc.place_order(session, user, product_id=body.product_id, qty=body.qty, pay_currency=body.pay_currency,
                                 idem=body.idempotency_key, inventory_item_id=body.inventory_item_id)
    return order_dict(o)


@router.get("/orders")
async def my_orders(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).limit(100))).scalars().all()
    return [order_dict(o) for o in rows]


class DisputeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/orders/{oid}/dispute")
async def dispute_order(oid: int, body: DisputeIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    o = (await session.execute(select(Order).where(Order.id == oid, Order.user_id == user.id).with_for_update())).scalar_one_or_none()
    if not o or o.status in ("refunded", "cancelled", "disputed"):
        raise not_found("Buyurtma topilmadi yoki nizo ochib bo'lmaydi")
    o.status = "disputed"
    session.add(Dispute(kind="dispute", ref_type="order", ref_id=o.id, opened_by=user.id, reason=body.reason))
    return order_dict(o)


# ------------------------------------------------------------------ ijara
@router.get("/rent/items")
async def rent_items(q: str | None = None, sort: str = "new", page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=60),
                     user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    stmt = select(InventoryItem).join(Product, Product.id == InventoryItem.product_id).where(
        InventoryItem.status == "available", Product.active.is_(True), Product.deleted_at.is_(None), Product.rent_enabled.is_(True))
    if q:
        stmt = stmt.where(or_(InventoryItem.name.ilike(f"%{q}%"), InventoryItem.item_ref.ilike(f"%{q}%")))
    stmt = _sort(stmt, sort, Product.rent_price_per_day).order_by(InventoryItem.id.desc()).limit(size).offset((page - 1) * size)
    items = (await session.execute(stmt)).scalars().unique().all()
    mm = await media_map(session, list({i.product_id for i in items}))
    return [item_card(i, mm, for_rent=True) for i in items]


@router.get("/rent/items/{item_id}/calendar")
async def rent_calendar(item_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return {"busy": await svc.calendar(session, item_id)}


class RentIn(BaseModel):
    inventory_item_id: int
    start_date: date
    days: int = Field(ge=1, le=365)
    pay_currency: str
    idempotency_key: str = Field(min_length=8, max_length=100)


@router.post("/rent")
async def rent(body: RentIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    o, r, _ = await svc.rent_item(session, user, inventory_item_id=body.inventory_item_id, start_date=body.start_date, days=body.days,
                                  pay_currency=body.pay_currency, idem=body.idempotency_key)
    return {"order": order_dict(o), "rental": rental_dict(r)}


@router.get("/rentals")
async def my_rentals(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Rental).where(Rental.user_id == user.id).order_by(Rental.id.desc()).limit(100))).scalars().unique().all()
    return [rental_dict(r) for r in rows]


class RateIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str | None = Field(None, max_length=500)


@router.post("/rentals/{rid}/rate")
async def rate_rental(rid: int, body: RateIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    r = await session.get(Rental, rid)
    if not r or r.user_id != user.id:
        raise not_found()
    if r.status != "returned":
        raise DomainError("bad_state", "Faqat qaytarilgan ijarani baholash mumkin", 409)
    if r.rating:
        raise DomainError("duplicate", "Allaqachon baholangan", 409)
    r.rating = body.rating
    session.add(Review(author_id=user.id, rental_id=r.id, rating=body.rating, text=body.text))
    return rental_dict(r)
