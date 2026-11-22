import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from conftest import credit, fund, user_id_of


async def test_daily_bonus_once_per_day(login):
    u = await login(2001)
    r = await u.post("/api/bonus/daily/claim")
    assert r.status_code == 200 and r.json()["amount"] == 5 and r.json()["streak"] == 1
    assert (await u.post("/api/bonus/daily/claim")).status_code == 409
    assert await u.balance() == 5
    assert (await u.get("/api/bonus/daily")).json()["claimed_today"] is True


async def test_daily_bonus_streak_ladder_and_reset(login):
    from app.db import SessionLocal
    from app.services import bonus
    u = await login(2002)
    uid = await user_id_of(u.abu_id)
    base = datetime(2026, 3, 1, 8, tzinfo=timezone.utc)
    got = []
    for d in range(7):  # 7 kun ketma-ket
        async with SessionLocal() as s, s.begin():
            got.append((await bonus.claim_daily(s, uid, now=base + timedelta(days=d)))["amount"])
    assert got == [5, 5, 10, 10, 10, 10, 25]
    async with SessionLocal() as s, s.begin():  # 1 kun tashlab ketildi -> streak 1
        r = await bonus.claim_daily(s, uid, now=base + timedelta(days=9))
    assert r["streak"] == 1 and r["amount"] == 5
    async with SessionLocal() as s:  # shu kunga qayta
        with pytest.raises(Exception, match="allaqachon"):
            async with s.begin():
                await bonus.claim_daily(s, uid, now=base + timedelta(days=9, hours=2))


async def test_parallel_daily_claims_pay_once(login):
    u = await login(2003)
    rs = await asyncio.gather(*[u.post("/api/bonus/daily/claim") for _ in range(5)])
    assert sorted(r.status_code for r in rs) == [200, 409, 409, 409, 409]
    assert await u.balance() == 5


async def _make_referral(login, tg_a=2010, tg_b=2011):
    a = await login(tg_a)
    b = await login(tg_b, start_param=f"ref_{a.me['referral_code']}")
    return a, b


async def _qualify_now():
    from app.db import engine
    async with engine.begin() as c:
        await c.execute(text("UPDATE referrals SET qualifies_at = now() - interval '1 minute'"))


async def _process():
    from app.db import SessionLocal
    from app.services import bonus
    async with SessionLocal() as s, s.begin():
        return await bonus.process_pending_referrals(s)


async def test_referral_rewarded_once_after_wait(login):
    a, b = await _make_referral(login)
    assert await _process() == 0  # 2 soat kutish tugamagan
    await _qualify_now()
    assert await _process() == 1
    assert await _process() == 0  # takror mukofot yo'q
    assert await a.balance("ABU_F") == 50 and await a.balance("ABU_TON") == 2
    assert await b.balance("ABU_F") == 0
    r = (await a.get("/api/referral")).json()
    assert r["counts"]["rewarded"] == 1 and "ref_" in r["link"]


async def test_referral_requires_subscription_server_side(login):
    from app.db import SessionLocal
    from app.models import MandatoryChannel
    from app.services import channels
    async with SessionLocal() as s, s.begin():
        s.add(MandatoryChannel(chat_id="@testkanal", title="Test"))
    state = {"ok": False}

    async def checker(chat, tg):
        return state["ok"]
    channels.set_member_checker(checker)
    a, b = await _make_referral(login, 2020, 2021)
    await _qualify_now()
    assert await _process() == 0 and await a.balance() == 0  # obuna yo'q
    state["ok"] = True
    assert await _process() == 1 and await a.balance() == 50
    channels.set_member_checker(None)


async def test_referral_abuse_protection(login):
    from app.db import SessionLocal
    from app.models import User
    from app.services import users
    a = await login(2030)
    b = await login(2031, start_param=f"ref_{a.me['referral_code']}")
    await login(2031, start_param=f"ref_{a.me['referral_code']}")  # mavjud foydalanuvchini qayta taklif qilib bo'lmaydi
    async with SessionLocal() as s, s.begin():
        me = await s.get(User, await user_id_of(a.abu_id))
        assert await users.register_referral(s, me, me.referral_code) is None  # o'zini o'zi taklif qilish
    c = await login(2032, start_param=f"ref_{a.me['referral_code']}")
    await _qualify_now()
    assert await _process() == 2 and await a.balance() == 100


async def test_promo_modes_and_limits(login, admin):
    mk = lambda **kw: admin.post("/api/admin/promo", {"currency": "ABU_F", "amount": 10, **kw})
    assert (await mk(code="BAD1", mode="limited_uses")).status_code == 400  # limit kerak
    assert (await mk(code="BAD2", mode="unlimited", max_uses=5)).status_code == 400
    assert (await mk(code="BAD3", mode="time_limited", max_uses=5, expires_at="2099-01-01T00:00:00Z")).status_code == 400
    assert (await mk(code="LIM", mode="limited_uses", max_uses=1)).status_code == 200
    assert (await mk(code="EXP", mode="time_limited", expires_at="2099-01-01T00:00:00Z")).status_code == 200
    assert (await mk(code="UNL", mode="unlimited")).status_code == 200
    u1, u2 = await login(2040), await login(2041)
    assert (await u1.post("/api/promo/redeem", {"code": "lim"})).status_code == 200  # katta-kichik harf farqi yo'q
    assert (await u1.post("/api/promo/redeem", {"code": "LIM"})).status_code == 409  # bir foydalanuvchi bir marta
    assert (await u2.post("/api/promo/redeem", {"code": "LIM"})).status_code == 410  # limit tugadi
    for u in (u1, u2):
        assert (await u.post("/api/promo/redeem", {"code": "UNL"})).status_code == 200
    from app.db import engine
    async with engine.begin() as c:
        await c.execute(text("UPDATE promo_codes SET expires_at = now() - interval '1 hour' WHERE code='EXP'"))
    assert (await u1.post("/api/promo/redeem", {"code": "EXP"})).status_code == 410  # muddat tugagan
    assert (await u1.post("/api/promo/redeem", {"code": "NOPE"})).status_code == 404
    assert await u1.balance() == 20


async def test_parallel_promo_redeem_by_many_respects_limit(login, admin):
    await admin.post("/api/admin/promo", {"code": "ONE", "mode": "limited_uses", "currency": "ABU_TON", "amount": 3, "max_uses": 2})
    users = [await login(2050 + i) for i in range(5)]
    rs = await asyncio.gather(*[u.post("/api/promo/redeem", {"code": "ONE"}) for u in users])
    assert sorted(r.status_code for r in rs).count(200) == 2


async def test_gift_rules_and_review(login, admin):
    a, b = await login(2060), await login(2061)
    await fund(a, "ABU_F", 10_000)
    k = lambda: uuid.uuid4().hex
    body = lambda **kw: {"to_abu_id": b.abu_id, "currency": "ABU_F", "amount": 10, "idempotency_key": k(), **kw}
    assert (await a.post("/api/gifts", body())).status_code == 403  # yangi akkaunt cheklovi
    await admin.put("/api/admin/settings/gift_min_account_age_hours", {"value": 0})
    assert (await a.post("/api/gifts", body(to_abu_id=a.abu_id))).status_code == 400
    r = await a.post("/api/gifts", body(amount=100))
    assert r.status_code == 200 and r.json()["status"] == "completed" and await b.balance() == 100
    assert (await a.post("/api/gifts", body(amount=4901))).status_code == 429  # kunlik limit 5000
    big = await a.post("/api/gifts", body(amount=2500))  # tekshiruv chegarasidan katta
    assert big.json()["status"] == "pending_review" and await b.balance() == 100 and await a.balance() == 10_000 - 2600
    gid = (await admin.get("/api/admin/gifts")).json()[0]["id"]
    assert (await admin.post(f"/api/admin/gifts/{gid}/review", {"approve": True})).status_code == 200
    assert (await admin.post(f"/api/admin/gifts/{gid}/review", {"approve": False})).status_code == 409
    assert await b.balance() == 2600
    rej = await a.post("/api/gifts", body(amount=2100))
    gid2 = next(g["id"] for g in (await admin.get("/api/admin/gifts")).json())
    await admin.post(f"/api/admin/gifts/{gid2}/review", {"approve": False})
    assert await a.balance() == 10_000 - 2600 and await b.balance() == 2600  # rad etilsa pul qaytadi


async def test_daily_question_once_and_friends_duel(login):
    u, v = await login(2070), await login(2071)
    q = (await u.get("/api/question/today")).json()
    assert q["available"] and "correct_index" not in q
    assert (await u.post("/api/question/answer", {"index": 0})).status_code == 200
    assert (await u.post("/api/question/answer", {"index": 0})).status_code == 409
    assert (await u.post("/api/duels", {"abu_id": v.abu_id})).status_code == 403  # do'st emas
    fr = (await u.post("/api/friends/request", {"abu_id": v.abu_id})).json()
    assert (await u.post(f"/api/friends/{fr['id']}/accept")).status_code == 404  # so'rovni faqat qabul qiluvchi tasdiqlaydi
    assert (await v.post(f"/api/friends/{fr['id']}/accept")).status_code == 200
    d = (await u.post("/api/duels", {"abu_id": v.abu_id})).json()
    assert (await v.post(f"/api/duels/{d['id']}/accept", {"accept": True})).status_code == 200
    for p in (u, v):
        assert (await p.post(f"/api/duels/{d['id']}/answer", {"answers": [0, 0, 0]})).status_code == 200
    assert all(x["status"] == "finished" for x in (await u.get("/api/duels")).json())


async def test_tasks_verified_by_server(login):
    u = await login(2080)
    tasks = (await u.get("/api/tasks")).json()
    t = next(x for x in tasks if x["kind"] == "first_topup")
    assert (await u.post(f"/api/tasks/{t['id']}/claim")).status_code == 409  # shart bajarilmagan
