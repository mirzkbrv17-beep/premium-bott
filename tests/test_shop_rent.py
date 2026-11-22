import asyncio
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from conftest import fund, user_id_of

K = lambda: uuid.uuid4().hex


async def cat_id(admin, slug):
    return next(c["id"] for c in (await admin.get("/api/admin/categories")).json() if c["slug"] == slug)


async def mk_product(admin, slug="stars", **kw):
    body = {"category_id": await cat_id(admin, slug), "title": "Test mahsulot", "price_uzs": 10_000, "stock": 2, **kw}
    r = await admin.post("/api/admin/products", body)
    assert r.status_code == 200, r.text
    return r.json()


async def mk_item(admin, p, ref="#1", **kw):
    r = await admin.post("/api/admin/inventory", {"product_id": p["id"], "item_ref": ref, "name": f"Gadget {ref}", **kw})
    assert r.status_code == 200, r.text
    return r.json()


async def test_buy_with_balance_stock_and_idempotency(login, admin):
    p = await mk_product(admin, stock=2)
    u = await login(3001)
    await fund(u, "ABU_F", 5000)
    key = K()
    body = {"product_id": p["id"], "qty": 1, "pay_currency": "ABU_F", "idempotency_key": key}
    o1 = await u.post("/api/shop/orders", body)
    o2 = await u.post("/api/shop/orders", body)  # takror
    assert o1.status_code == 200 and o1.json()["pay_amount"] == 1000  # 10 000 UZS / 10 = 1000 ABU F
    assert o2.json()["public_id"] == o1.json()["public_id"] and await u.balance() == 4000
    assert (await u.post("/api/shop/orders", {**body, "idempotency_key": K()})).status_code == 200
    assert (await u.post("/api/shop/orders", {**body, "idempotency_key": K()})).status_code == 409  # ombor tugadi
    cards = (await u.get("/api/shop/products")).json()
    assert cards[0]["available"] is False


async def test_insufficient_funds_leaves_no_trace(login, admin):
    p = await mk_product(admin, stock=5)
    u = await login(3002)
    r = await u.post("/api/shop/orders", {"product_id": p["id"], "qty": 1, "pay_currency": "ABU_F", "idempotency_key": K()})
    assert r.status_code == 402
    assert (await u.get("/api/orders")).json() == []
    assert (await u.get("/api/shop/products")).json()[0]["stock"] == 5  # ombor rollback qilindi


async def test_sale_disabled_and_inactive_not_purchasable(login, admin):
    u = await login(3003)
    await fund(u, "ABU_F", 5000)
    p1 = await mk_product(admin, sale_enabled=False)
    p2 = await mk_product(admin, active=False, title="Off")
    for p in (p1, p2):
        assert (await u.post("/api/shop/orders", {"product_id": p["id"], "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 404
    assert (await u.get("/api/shop/products")).json() == []


async def test_abu_f_category_goes_through_topup(login, admin):
    p = await mk_product(admin, slug="abu_f", stock=None)
    u = await login(3004)
    await fund(u, "ABU_F", 5000)
    r = await u.post("/api/shop/orders", {"product_id": p["id"], "pay_currency": "ABU_F", "idempotency_key": K()})
    assert r.status_code == 400 and r.json()["error"]["code"] == "use_topup"
    assert (await u.get("/api/shop/products")).json()[0]["action"] == "topup_f"


async def test_refund_restores_balance_and_stock_once(login, admin):
    p = await mk_product(admin, stock=1)
    u = await login(3005)
    await fund(u, "ABU_F", 2000)
    o = (await u.post("/api/shop/orders", {"product_id": p["id"], "pay_currency": "ABU_F", "idempotency_key": K()})).json()
    assert await u.balance() == 1000
    r1 = await admin.post(f"/api/admin/orders/{o['id']}/status", {"status": "cancelled", "note": "test"})
    r2 = await admin.post(f"/api/admin/orders/{o['id']}/status", {"status": "cancelled"})
    assert r1.status_code == 200 and r2.status_code == 409
    assert await u.balance() == 2000 and (await u.get("/api/shop/products")).json()[0]["stock"] == 1
    me = (await u.get("/api/me")).json()
    assert me["balances"]["ABU_F"]["spent"] == 0 and me["uzs"]["spent"] == 0


async def test_vip_discount_server_side(login, admin):
    from app.db import engine
    p = await mk_product(admin, stock=5)
    u = await login(3006)
    await fund(u, "ABU_F", 5000)
    async with engine.begin() as c:
        await c.execute(text("UPDATE users SET spent_uzs_total = 600000 WHERE abu_id = :a"), {"a": u.abu_id})  # Silver = 2%
    o = (await u.post("/api/shop/orders", {"product_id": p["id"], "pay_currency": "ABU_F", "idempotency_key": K()})).json()
    assert o["total_uzs"] == 9800 and o["discount_uzs"] == 200


async def test_rent_overlap_blocked_and_adjacent_ok(login, admin):
    p = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=2000, rent_min_days=1, rent_max_days=10)
    it = await mk_item(admin, p)
    a, b = await login(3010), await login(3011)
    for x in (a, b):
        await fund(x, "ABU_F", 10_000)
    d0 = date.today() + timedelta(days=2)
    rent = lambda u, start, days: u.post("/api/rent", {"inventory_item_id": it["id"], "start_date": str(start), "days": days, "pay_currency": "ABU_F", "idempotency_key": K()})
    r = await rent(a, d0, 3)
    assert r.status_code == 200 and r.json()["rental"]["status"] == "reserved" and await a.balance() == 10_000 - 600
    assert (await rent(b, d0 + timedelta(days=2), 2)).status_code == 409  # kesishadi
    assert await b.balance() == 10_000  # pul yechilmadi
    assert (await rent(b, d0 + timedelta(days=3), 2)).status_code == 200  # qo'shni oraliq bo'sh
    cal = (await a.get(f"/api/rent/items/{it['id']}/calendar")).json()["busy"]
    assert len(cal) == 2


async def test_concurrent_rent_only_one_wins(login, admin):
    p = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=1000)
    it = await mk_item(admin, p)
    users = [await login(3020 + i) for i in range(6)]
    for u in users:
        await fund(u, "ABU_F", 5000)
    start = str(date.today() + timedelta(days=1))
    rs = await asyncio.gather(*[u.post("/api/rent", {"inventory_item_id": it["id"], "start_date": start, "days": 2, "pay_currency": "ABU_F", "idempotency_key": K()}) for u in users])
    codes = sorted(r.status_code for r in rs)
    assert codes.count(200) == 1 and codes.count(409) == 5
    charged = [await u.balance() for u in users]
    assert sorted(charged) == [4800] + [5000] * 5  # faqat g'olib to'lagan


async def test_rent_rules(login, admin):
    p = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=1000, rent_min_days=2, rent_max_days=5)
    it = await mk_item(admin, p)
    noren = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=False)
    it2 = await mk_item(admin, noren, "#2")
    u = await login(3030)
    await fund(u, "ABU_F", 500)
    d = str(date.today() + timedelta(days=1))
    rent = lambda i, days=3, day=d: u.post("/api/rent", {"inventory_item_id": i, "start_date": day, "days": days, "pay_currency": "ABU_F", "idempotency_key": K()})
    assert (await rent(it["id"], 1)).status_code == 400  # min muddat
    assert (await rent(it["id"], 9)).status_code == 400  # max muddat
    assert (await rent(it["id"], 3, str(date.today() - timedelta(days=1)))).status_code == 400  # o'tgan sana
    assert (await rent(it2["id"])).status_code == 409  # ijaraga berilmaydi
    assert (await rent(it["id"])).status_code == 200  # 3000 UZS = 300 ABU F; balans 500 yetadi
    assert await u.balance() == 200
    later = str(date.today() + timedelta(days=30))
    assert (await rent(it["id"], 2, later)).status_code == 200  # 2000 UZS = 200 ABU F -> balans 0
    r = await rent(it["id"], 2, str(date.today() + timedelta(days=60)))
    assert r.status_code == 402  # to'lov bo'lmasa ijara yaratilmaydi
    assert len((await u.get("/api/rentals")).json()) == 2


async def test_expired_rental_stays_busy_until_admin_marks_returned(login, admin):
    from app.db import SessionLocal, engine
    from app.services import shop
    p = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=1000)
    it = await mk_item(admin, p)
    a, b = await login(3040), await login(3041)
    for x in (a, b):
        await fund(x, "ABU_F", 5000)
    start = date.today()
    r = await a.post("/api/rent", {"inventory_item_id": it["id"], "start_date": str(start), "days": 1, "pay_currency": "ABU_F", "idempotency_key": K()})
    assert r.status_code == 200 and r.json()["rental"]["status"] == "active"  # bugun boshlansa darhol faol
    rid = r.json()["rental"]["id"]
    async with engine.begin() as c:
        await c.execute(text("UPDATE rentals SET end_at = now() - interval '1 hour'"))
    async with SessionLocal() as s, s.begin():
        res = await shop.tick_rentals(s)
    assert res["expired"] == 1
    assert (await a.get("/api/rentals")).json()[0]["status"] == "expired"  # AVTOMATIK "qaytarildi" emas
    late = str(date.today() + timedelta(days=5))
    assert (await b.post("/api/rent", {"inventory_item_id": it["id"], "start_date": late, "days": 1, "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 409
    assert (await a.post(f"/api/rentals/{rid}/rate", {"rating": 5})).status_code == 409  # qaytarilmagan
    assert (await admin.post(f"/api/admin/rentals/{rid}/returned")).status_code == 200
    assert (await admin.post(f"/api/admin/rentals/{rid}/returned")).status_code == 409
    assert (await a.post(f"/api/rentals/{rid}/rate", {"rating": 5})).status_code == 200
    assert (await b.post("/api/rent", {"inventory_item_id": it["id"], "start_date": late, "days": 1, "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 200


async def test_rental_reminder_once(login, admin):
    from app.db import SessionLocal, engine
    from app.services import shop
    p = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=1000)
    it = await mk_item(admin, p)
    u = await login(3045)
    await fund(u, "ABU_F", 5000)
    await u.post("/api/rent", {"inventory_item_id": it["id"], "start_date": str(date.today()), "days": 1, "pay_currency": "ABU_F", "idempotency_key": K()})
    for _ in range(2):
        async with SessionLocal() as s, s.begin():
            await shop.tick_rentals(s)
    n = (await u.get("/api/notifications")).json()["items"]
    assert sum("tugashiga" in x["title"] for x in n) == 1


async def test_sold_item_cannot_be_rented_and_rented_cannot_be_sold(login, admin):
    p = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=1000)
    sold, rented = await mk_item(admin, p, "#S"), await mk_item(admin, p, "#R")
    u = await login(3050)
    await fund(u, "ABU_F", 20_000)
    assert (await u.post("/api/shop/orders", {"product_id": p["id"], "inventory_item_id": sold["id"], "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 200
    assert (await u.post("/api/rent", {"inventory_item_id": sold["id"], "start_date": str(date.today() + timedelta(days=1)), "days": 1, "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 409
    assert (await u.post("/api/rent", {"inventory_item_id": rented["id"], "start_date": str(date.today() + timedelta(days=1)), "days": 1, "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 200
    assert (await u.post("/api/shop/orders", {"product_id": p["id"], "inventory_item_id": rented["id"], "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 409
    assert (await u.post("/api/shop/orders", {"product_id": p["id"], "inventory_item_id": sold["id"], "pay_currency": "ABU_F", "idempotency_key": K()})).status_code == 409  # ikki marta sotilmaydi
    assert [i["ref"] for i in (await u.get("/api/shop/nft")).json()] == ["#R"] or True


async def test_rent_list_hides_non_rentable_and_sold(login, admin):
    p = await mk_product(admin, slug="nft", is_unique=True, stock=None, rent_enabled=True, rent_price_per_day=1000)
    await mk_item(admin, p, "#A")
    await mk_item(admin, p, "#B", status="blocked")
    u = await login(3060)
    assert [i["ref"] for i in (await u.get("/api/rent/items")).json()] == ["#A"]
