"""ABU BOT ma'lumotlar modeli. Pul miqdorlari faqat butun son (minor units) - float yo'q."""
from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        LargeBinary, Numeric, String, Text, UniqueConstraint, event)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")
ABU_F, ABU_TON = "ABU_F", "ABU_TON"
CURRENCIES = (ABU_F, ABU_TON)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # o'xshash belgilarsiz


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def rand_id(prefix: str, n: int = 10) -> str:
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(n))


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}


def ts(**kw):
    return mapped_column(DateTime(timezone=True), default=utcnow, **kw)


# ----------------------------------------------------------------------------- foydalanuvchi
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True)  # faqat serverda
    abu_id: Mapped[str] = mapped_column(String(16), unique=True, default=lambda: rand_id("ABU", 8))
    kind: Mapped[str] = mapped_column(String(10), default="user")  # user | system
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[Optional[str]] = mapped_column(String(128))
    username: Mapped[Optional[str]] = mapped_column(String(64))
    photo_url: Mapped[Optional[str]] = mapped_column(Text)
    language_code: Mapped[Optional[str]] = mapped_column(String(8))
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_reason: Mapped[Optional[str]] = mapped_column(Text)
    referral_code: Mapped[str] = mapped_column(String(16), unique=True, default=lambda: rand_id("R", 7))
    referred_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    xp: Mapped[int] = mapped_column(BigInteger, default=0)
    spent_uzs_total: Mapped[int] = mapped_column(BigInteger, default=0)  # VIP uchun
    bot_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = ts()
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False, lazy="selectin")


class UserProfile(Base):
    __tablename__ = "user_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    decoration: Mapped[Optional[str]] = mapped_column(String(32))
    bio: Mapped[Optional[str]] = mapped_column(String(200))
    user: Mapped[User] = relationship(back_populates="profile")


class UsedToken(Base):  # bir martalik admin-link tokenlari
    __tablename__ = "used_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = ts()


# ----------------------------------------------------------------------------- balans / ledger
class BalanceAccount(Base):
    __tablename__ = "balance_accounts"
    __table_args__ = (UniqueConstraint("user_id", "currency"), CheckConstraint("balance >= 0", name="ck_balance_nonneg"),
                      CheckConstraint("currency in ('ABU_F','ABU_TON')", name="ck_currency"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(8))
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    topped_up_total: Mapped[int] = mapped_column(BigInteger, default=0)
    spent_total: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = ts()


class LedgerEntry(Base):
    """O'zgarmas jurnal. UPDATE/DELETE ORM va (Postgres'da) trigger orqali taqiqlangan."""
    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_ledger_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tx_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("TX", 12))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("balance_accounts.id"))
    currency: Mapped[str] = mapped_column(String(8))
    amount: Mapped[int] = mapped_column(BigInteger)  # ishorali
    balance_after: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    ref_type: Mapped[Optional[str]] = mapped_column(String(32))
    ref_id: Mapped[Optional[str]] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    reverses_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ledger_entries.id"))
    note: Mapped[Optional[str]] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    admin_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = ts()


@event.listens_for(LedgerEntry, "before_update")
@event.listens_for(LedgerEntry, "before_delete")
def _ledger_immutable(mapper, connection, target):  # pragma: no cover - oddiy himoya
    raise RuntimeError("LedgerEntry o'zgarmas: tuzatish uchun reversal/adjustment yozuvi yarating")


class PaymentProvider(Base):
    __tablename__ = "payment_providers"
    code: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class TonPackage(Base):
    __tablename__ = "ton_packages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    units: Mapped[int] = mapped_column(BigInteger)
    price_uzs: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class TopUp(Base):
    __tablename__ = "topups"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"), UniqueConstraint("provider", "external_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("TOP", 12))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(8))
    units: Mapped[int] = mapped_column(BigInteger)
    uzs_amount: Mapped[int] = mapped_column(BigInteger)  # haqiqiy to'lov (UZS) - virtual balansdan alohida
    stars_amount: Mapped[Optional[int]] = mapped_column(BigInteger)
    rate_snapshot: Mapped[Optional[int]] = mapped_column(BigInteger)  # UZS / 1 birlik (butun)
    provider: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    receipt_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    receipt_mime: Mapped[Optional[str]] = mapped_column(String(40))
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ledger_tx_id: Mapped[Optional[str]] = mapped_column(String(24))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(24))
    event_id: Mapped[str] = mapped_column(String(120))
    result: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = ts()


# ----------------------------------------------------------------------------- katalog
class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="goods")  # goods|abu_f|abu_ton|nft
    name: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"uz":..,"ru":..,"en":..}
    icon: Mapped[str] = mapped_column(String(8), default="🎁")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("P", 6))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[Optional[str]] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    price_uzs: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    sale_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rent_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rent_price_per_day: Mapped[int] = mapped_column(BigInteger, default=0)
    rent_min_days: Mapped[int] = mapped_column(Integer, default=1)
    rent_max_days: Mapped[int] = mapped_column(Integer, default=30)
    stock: Mapped[Optional[int]] = mapped_column(Integer)  # None = cheksiz (xizmatlar)
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False)  # InventoryItem'lar bilan
    color: Mapped[str] = mapped_column(String(9), default="#2a2a35")
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = ts()
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    category: Mapped[Category] = relationship(lazy="joined")


class ProductMedia(Base):
    __tablename__ = "product_media"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    inventory_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_items.id"))
    kind: Mapped[str] = mapped_column(String(10))  # image|gif|webm|lottie|tgs
    mime: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size: Mapped[int] = mapped_column(Integer)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = ts()


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("product_id", "item_ref"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    item_ref: Mapped[str] = mapped_column(String(32))  # "#9400"
    name: Mapped[str] = mapped_column(String(120))
    attrs: Mapped[dict[str, Any]] = mapped_column(default=dict)  # model, backdrop
    color: Mapped[Optional[str]] = mapped_column(String(9))
    status: Mapped[str] = mapped_column(String(12), default="available")  # available|sold|blocked
    rent_price_per_day: Mapped[Optional[int]] = mapped_column(BigInteger)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()
    product: Mapped[Product] = relationship(lazy="joined")


# ----------------------------------------------------------------------------- buyurtma / ijara
class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("ORD", 10))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="sale")  # sale|rent
    status: Mapped[str] = mapped_column(String(16), default="paid", index=True)
    # paid -> processing -> completed | cancelled | refunded | disputed
    total_uzs: Mapped[int] = mapped_column(BigInteger)
    discount_uzs: Mapped[int] = mapped_column(BigInteger, default=0)
    pay_currency: Mapped[str] = mapped_column(String(8))
    pay_amount: Mapped[int] = mapped_column(BigInteger)
    rate_snapshot: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    delivery_note: Mapped[Optional[str]] = mapped_column(Text)
    ledger_tx_id: Mapped[Optional[str]] = mapped_column(String(24))
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    items: Mapped[list["OrderItem"]] = relationship(lazy="selectin")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    inventory_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_items.id"))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_uzs: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(160))


class Rental(Base):
    __tablename__ = "rentals"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("RNT", 10))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    days: Mapped[int] = mapped_column(Integer)
    price_per_day_uzs: Mapped[int] = mapped_column(BigInteger)
    total_uzs: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12), default="reserved", index=True)
    # reserved -> active -> expired (qaytarish kutilmoqda) -> returned | cancelled | disputed
    remind_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    returned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = ts()
    item: Mapped[InventoryItem] = relationship(lazy="joined")


class RentalAvailability(Base):  # admin qo'ygan bloklash oynalari
    __tablename__ = "rental_availability"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(String(200))


# ----------------------------------------------------------------------------- market
class SellerProfile(Base):
    __tablename__ = "seller_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    bio: Mapped[Optional[str]] = mapped_column(String(300))
    verification_status: Mapped[str] = mapped_column(String(10), default="none")  # none|pending|verified|rejected
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    rating_avg: Mapped[int] = mapped_column(Integer, default=0)  # x100
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    sales_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = ts()


class MarketListing(Base):
    __tablename__ = "market_listings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("L", 8))
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    price_amount: Mapped[int] = mapped_column(BigInteger)
    price_currency: Mapped[str] = mapped_column(String(8))  # ABU_F | ABU_TON
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending(moderatsiya)|active|hidden|sold_out|rejected|removed
    moderation_note: Mapped[Optional[str]] = mapped_column(String(300))
    promoted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MarketOrder(Base):
    __tablename__ = "market_orders"
    __table_args__ = (UniqueConstraint("buyer_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("MO", 10))
    listing_id: Mapped[int] = mapped_column(ForeignKey("market_listings.id"))
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    commission: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(12), default="held")
    # held(escrow) -> delivered -> completed | disputed -> refunded/completed | cancelled(refund)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120), default="")
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = ts()


class MarketMessage(Base):
    __tablename__ = "market_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market_order_id: Mapped[int] = mapped_column(ForeignKey("market_orders.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = ts()


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    market_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("market_orders.id"), unique=True)
    rental_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rentals.id"), unique=True)
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = ts()


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="dispute")  # dispute|report
    ref_type: Mapped[str] = mapped_column(String(16))  # market_order|order|rental|listing
    ref_id: Mapped[int] = mapped_column(BigInteger)
    opened_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(500))
    resolved_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = ts()
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ----------------------------------------------------------------------------- bonus / ijtimoiy
class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    mode: Mapped[str] = mapped_column(String(14))  # limited_uses | time_limited | unlimited
    currency: Mapped[str] = mapped_column(String(8))
    amount: Mapped[int] = mapped_column(BigInteger)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts()
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (UniqueConstraint("user_id", "promo_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"))
    created_at: Mapped[datetime] = ts()


class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    invited_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending|rewarded|rejected|flagged
    qualifies_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rewarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    note: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = ts()


class MandatoryChannel(Base):
    __tablename__ = "mandatory_channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(64))  # @username yoki -100...
    title: Mapped[str] = mapped_column(String(120), default="")
    invite_url: Mapped[Optional[str]] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class DailyBonusClaim(Base):
    __tablename__ = "daily_bonus_claims"
    __table_args__ = (UniqueConstraint("user_id", "claim_date"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    claim_date: Mapped[date] = mapped_column(Date)
    streak: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = ts()


class VIPTier(Base):
    __tablename__ = "vip_tiers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    rank: Mapped[int] = mapped_column(Integer, unique=True)
    min_spent_uzs: Mapped[int] = mapped_column(BigInteger)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    badge: Mapped[str] = mapped_column(String(8), default="🥉")
    perks: Mapped[list[Any]] = mapped_column(default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Achievement(Base):
    __tablename__ = "achievements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(200), default="")
    icon: Mapped[str] = mapped_column(String(8), default="🏆")
    metric: Mapped[str] = mapped_column(String(24))  # orders|topups|streak|referrals|xp|spent_uzs|gifts|rentals
    threshold: Mapped[int] = mapped_column(BigInteger)
    xp_reward: Mapped[int] = mapped_column(Integer, default=20)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    achievement_id: Mapped[int] = mapped_column(ForeignKey("achievements.id"))
    created_at: Mapped[datetime] = ts()


class XpEvent(Base):
    __tablename__ = "xp_events"
    __table_args__ = (Index("ix_xp_created", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = ts()


class GiftTransfer(Base):
    __tablename__ = "gift_transfers"
    __table_args__ = (UniqueConstraint("sender_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, default=lambda: rand_id("GFT", 10))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(8))
    amount: Mapped[int] = mapped_column(BigInteger)
    message: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="completed")  # completed|pending_review|rejected
    idempotency_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = ts()


class Friend(Base):
    __tablename__ = "friends"
    __table_args__ = (UniqueConstraint("user_id", "friend_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # so'rov yuboruvchi
    friend_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|accepted
    created_at: Mapped[datetime] = ts()


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(String(300))
    options: Mapped[list[Any]] = mapped_column(default=list)
    correct_index: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DailyQuestionAnswer(Base):
    __tablename__ = "daily_question_answers"
    __table_args__ = (UniqueConstraint("user_id", "answer_date"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    answer_date: Mapped[date] = mapped_column(Date)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    correct: Mapped[bool] = mapped_column(Boolean)


class Duel(Base):  # pul tikishsiz viktorina duel
    __tablename__ = "duels"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    challenger_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    opponent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question_ids: Mapped[list[Any]] = mapped_column(default=list)
    challenger_score: Mapped[Optional[int]] = mapped_column(Integer)
    opponent_score: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="invited")  # invited|active|finished|declined
    winner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()


class News(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts()


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # first_order|first_topup|invite_1|streak_3|join_channel|level_5
    param: Mapped[Optional[str]] = mapped_column(String(64))  # join_channel uchun chat_id
    currency: Mapped[str] = mapped_column(String(8), default=ABU_F)
    amount: Mapped[int] = mapped_column(BigInteger, default=10)
    xp: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserTask(Base):
    __tablename__ = "user_tasks"
    __table_args__ = (UniqueConstraint("user_id", "task_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = ts()


# ----------------------------------------------------------------------------- bildirishnoma / support
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # order|rental|payment|bonus|product|promo|referral|support|market
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(1000), default="")
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # botga yuborilgan vaqt
    send_attempts: Mapped[int] = mapped_column(Integer, default=0)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = ts()


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open|answered|closed
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = ts()


# ----------------------------------------------------------------------------- admin
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(24), unique=True)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"), primary_key=True)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts()
    role: Mapped[Role] = relationship(lazy="joined")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    admin_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(32))
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    created_at: Mapped[datetime] = ts()


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
