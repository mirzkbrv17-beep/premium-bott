from datetime import datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.sqltypes import LargeBinary

from .models import InventoryItem, Product, ProductMedia
from .services import shop as shop_svc


def row(obj: Any, exclude: tuple = ()) -> dict:
    """Generik serializer: LargeBinary ustunlar chiqarilmaydi."""
    out = {}
    for c in sa_inspect(obj).mapper.column_attrs:
        col = c.columns[0]
        if isinstance(col.type, LargeBinary) or c.key in exclude:
            continue
        v = getattr(obj, c.key)
        out[c.key] = v.isoformat() if isinstance(v, datetime) else (v.isoformat() if hasattr(v, "isoformat") else v)
    return out


async def media_map(session: AsyncSession, product_ids: list[int]) -> dict:
    """{(product_id, item_id|None): {id, kind}} - birinchi media (data yuklanmaydi)."""
    if not product_ids:
        return {}
    q = select(ProductMedia.id, ProductMedia.product_id, ProductMedia.inventory_item_id, ProductMedia.kind) \
        .where(ProductMedia.product_id.in_(product_ids)).order_by(ProductMedia.sort, ProductMedia.id)
    m: dict = {}
    for mid, pid, iid, kind in (await session.execute(q)).all():
        m.setdefault((pid, iid), {"id": mid, "kind": kind, "url": f"/api/media/{mid}"})
    return m


def media_for(m: dict, pid: int, iid: int | None = None):
    return (m.get((pid, iid)) if iid else None) or m.get((pid, None))


async def product_card(session: AsyncSession, p: Product, media: dict) -> dict:
    st = await shop_svc.stock_info(session, p)
    action = {"abu_f": "topup_f", "abu_ton": "topup_ton"}.get(p.category.kind, "buy")
    return {"type": "product", "id": p.id, "public_id": p.public_id, "title": p.title, "subtitle": p.subtitle,
            "description": p.description, "price_uzs": p.price_uzs, "final_price_uzs": shop_svc.unit_price(p),
            "discount_percent": p.discount_percent, "color": p.color, "category": p.category.slug,
            "category_kind": p.category.kind, "action": action, "available": st["available"], "stock": st["count"],
            "media": media_for(media, p.id), "meta": p.meta}


def item_card(it: InventoryItem, media: dict, for_rent: bool = False) -> dict:
    p = it.product
    d = {"type": "item", "id": it.id, "product_id": p.id, "ref": it.item_ref, "title": it.name,
         "subtitle": " • ".join(str(v) for v in (it.attrs or {}).values()) or p.subtitle, "attrs": it.attrs,
         "color": it.color or p.color, "price_uzs": shop_svc.unit_price(p), "category": p.category.slug,
         "media": media_for(media, p.id, it.id), "available": it.status == "available"}
    if for_rent:
        d.update({"rent_price_per_day": it.rent_price_per_day or p.rent_price_per_day, "min_days": p.rent_min_days,
                  "max_days": p.rent_max_days})
    return d


def order_dict(o) -> dict:
    return {"id": o.id, "public_id": o.public_id, "kind": o.kind, "status": o.status, "total_uzs": o.total_uzs,
            "discount_uzs": o.discount_uzs, "pay_currency": o.pay_currency, "pay_amount": o.pay_amount,
            "delivery_note": o.delivery_note, "created_at": o.created_at.isoformat(),
            "items": [{"title": i.title, "qty": i.qty, "unit_price_uzs": i.unit_price_uzs, "product_id": i.product_id} for i in o.items]}


def rental_dict(r) -> dict:
    return {"id": r.id, "public_id": r.public_id, "item": r.item.name, "item_id": r.inventory_item_id, "product_id": r.product_id,
            "start_at": r.start_at.isoformat(), "end_at": r.end_at.isoformat(), "days": r.days, "total_uzs": r.total_uzs,
            "status": r.status, "rating": r.rating, "returned_at": r.returned_at.isoformat() if r.returned_at else None}


def topup_dict(t) -> dict:
    return {"id": t.public_id, "currency": t.currency, "units": t.units, "uzs_amount": t.uzs_amount, "stars_amount": t.stars_amount,
            "provider": t.provider, "status": t.status, "created_at": t.created_at.isoformat(),
            "has_receipt": bool(t.receipt_mime), "review_note": t.review_note, "ledger_tx_id": t.ledger_tx_id}


def listing_dict(li, seller=None) -> dict:
    d = {"id": li.id, "public_id": li.public_id, "category": li.category, "title": li.title, "description": li.description,
         "price_amount": li.price_amount, "price_currency": li.price_currency, "quantity": li.quantity, "status": li.status,
         "promoted": bool(li.promoted_until and li.promoted_until.timestamp() > datetime.now().timestamp()),
         "views": li.views, "created_at": li.created_at.isoformat(), "moderation_note": li.moderation_note}
    if seller is not None:
        d["seller"] = seller
    return d
