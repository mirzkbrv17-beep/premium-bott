"""Demo ma'lumotlar (faqat dev/test). Ishga tushirish: cd backend && python -m app.seed_demo
Real mahsulot/narx/kanal admin panelda kiritiladi; bu faqat ekranlarni ko'rish uchun."""
import asyncio

from sqlalchemy import select

from .db import SessionLocal
from .models import Category, InventoryItem, MandatoryChannel, Product, ProductMedia
from .config import settings


async def main():
    if settings.is_prod:
        raise SystemExit("prod'da demo seed ishlatilmaydi")
    async with SessionLocal() as s, s.begin():
        cats = {c.slug: c for c in (await s.execute(select(Category))).scalars()}
        if not (await s.execute(select(Product.id).limit(1))).first():
            p1 = Product(category_id=cats["premium"].id, title="Telegram Premium 3 oy", subtitle="Premium obuna", price_uzs=150_000, color="#2b2a4c", stock=None)
            p2 = Product(category_id=cats["stars"].id, title="100 Telegram Stars", subtitle="⭐ Stars", price_uzs=24_000, color="#4a3a10", stock=None)
            p3 = Product(category_id=cats["gifts"].id, title="Lol Pop", subtitle="Cotton Candy", price_uzs=3_500, color="#1f5e5a", stock=10,
                         rent_enabled=True, rent_price_per_day=190, rent_min_days=4, rent_max_days=34)
            p4 = Product(category_id=cats["nft"].id, title="Winter Wreath", subtitle="Coloring Book · Camo", price_uzs=58_545, color="#2d4a2f",
                         is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=190, rent_min_days=3, rent_max_days=180)
            s.add_all([p1, p2, p3, p4])
            await s.flush()
            s.add_all([InventoryItem(product_id=p4.id, item_ref="#58545", name="Winter Wreath #58545", attrs={"model": "Coloring Book", "backdrop": "Camo G..."}, color="#2d4a2f"),
                       InventoryItem(product_id=p4.id, item_ref="#7321", name="Big Year #7321", attrs={"model": "A New Hope", "backdrop": "Hunter Green"}, color="#2f6b3a", rent_price_per_day=190)])
        if not (await s.execute(select(MandatoryChannel.id).limit(1))).first():
            s.add(MandatoryChannel(chat_id="@abu_channel_demo", title="ABU kanali", invite_url="https://t.me/abu_channel_demo"))
    print("demo seed tayyor")


if __name__ == "__main__":
    asyncio.run(main())
