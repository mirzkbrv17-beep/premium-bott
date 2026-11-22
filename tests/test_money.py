"""Balans, to'lov, webhook, idempotentlik, ledger testlari."""
import asyncio
import uuid

import pytest
from sqlalchemy import select, text

from conftest import credit, fund, sign, user_id_of


async def new_topup(u, currency="ABU_F", provider="mock", units=100, package_id=None):
    body = {"currency": currency, "provider": provider, "idempotency_key": uuid.uuid4().hex, "units": units, "package_id": package_id}
    r = await u.post("/api/topup", json=body)
    assert r.status_code == 200, r.text
    return r.json()["topup"]


async def test_balances_do_not_mix(login):
    from app.db import SessionLocal
    from app.services import ledger
    u = await login(1001)
    uid = await user_id_of(u.abu_id)
    await credit(uid, "ABU_F", 500)
    await credit(uid, "ABU_TON", 7)
    me = (await u.get("/api/me")).json()["balances"]
    assert me["ABU_F"]["balance"] == 500 and me["ABU_TON"]["balance"] == 7
    async with SessionLocal() as s, s.begin():
        await ledger.post_entry(s, user_id=uid, currency="ABU_F", amount=-100, kind="purchase", idem="x1")
    me = (await u.get("/api/me")).json()["balances"]
    assert me["ABU_F"]["balance"] == 400 and me["ABU_F"]["spent"] == 100 and me["ABU_TON"]["balance"] == 7


async def test_balance_never_negative(login):
    from app.db import SessionLocal
    from app.errors import InsufficientFunds
    from app.services import ledger
    u = await login(1002)
    with pytest.raises(InsufficientFunds):
        async with SessionLocal() as s, s.begin():
            await ledger.post_entry(s, user_id=await user_id_of(u.abu_id), currency="ABU_F", amount=-1, kind="purchase", idem="neg")


async def test_ledger_is_immutable(login):
    from app.db import SessionLocal, engine
    from app.models import LedgerEntry
    u = await login(1003)
    await credit(await user_id_of(u.abu_id), "ABU_F", 50)
    async with SessionLocal() as s:  # ORM himoyasi
        e = (await s.execute(select(LedgerEntry))).scalars().first()
        e.amount = 999
        with pytest.raises(RuntimeError):
            await s.flush()
    async with engine.begin() as c:  # DB trigger
        with pytest.raises(Exception, match="o'zgarmas"):
            await c.execute(text("UPDATE ledger_entries SET amount = 1"))


async def test_ledger_idempotency(login):
    from app.db import SessionLocal
    u = await login(1004)
    uid = await user_id_of(u.abu_id)
    await credit(uid, "ABU_F", 100, key="same")
    await credit(uid, "ABU_F", 100, key="same")
    assert await u.balance() == 100


async def test_duplicate_webhook_credits_once(login, client):
    u = await login(1010)
    t = await new_topup(u, units=100)
    raw, h = sign({"event_id": "evt-1", "order_id": t["id"], "amount": t["uzs_amount"], "status": "success"})
    r1 = await client.post("/api/webhooks/mock", content=raw, headers=h)
    r2 = await client.post("/api/webhooks/mock", content=raw, headers=h)
    assert r1.status_code == r2.status_code == 200 and r2.json()["result"] == "duplicate"
    # boshqa event_id bilan ham takroriy to'lov ikki marta qo'shilmaydi
    raw2, h2 = sign({"event_id": "evt-2", "order_id": t["id"], "amount": t["uzs_amount"], "status": "success"})
    assert (await client.post("/api/webhooks/mock", content=raw2, headers=h2)).json()["result"] == "already_processed"
    assert await u.balance() == 100


async def test_parallel_webhooks_credit_once(login, client):
    u = await login(1011)
    t = await new_topup(u, units=50)
    raw, h = sign({"event_id": "evt-p", "order_id": t["id"], "amount": t["uzs_amount"], "status": "success"})
    rs = await asyncio.gather(*[client.post("/api/webhooks/mock", content=raw, headers=h) for _ in range(5)])
    assert all(r.status_code == 200 for r in rs)
    assert await u.balance() == 50


async def test_bad_signature_rejected(login, client):
    u = await login(1012)
    t = await new_topup(u)
    raw, h = sign({"event_id": "e", "order_id": t["id"], "amount": t["uzs_amount"], "status": "success"})
    h["X-Signature"] = "0" * 64
    assert (await client.post("/api/webhooks/mock", content=raw, headers=h)).status_code == 401
    assert (await client.post("/api/webhooks/mock", content=raw, headers={"Content-Type": "application/json"})).status_code == 401
    assert await u.balance() == 0


async def test_wrong_amount_rejected(login, client):
    u = await login(1013)
    t = await new_topup(u)
    raw, h = sign({"event_id": "e-amt", "order_id": t["id"], "amount": t["uzs_amount"] - 1, "status": "success"})
    r = await client.post("/api/webhooks/mock", content=raw, headers=h)
    assert r.status_code == 400 and r.json()["error"] == "amount_mismatch"
    assert await u.balance() == 0


async def test_pending_payment_does_not_increase_balance(login):
    u = await login(1014)
    t = await new_topup(u)
    assert t["status"] == "pending" and await u.balance() == 0
    tx = (await u.get("/api/me/transactions")).json()["items"]
    assert tx[0]["status"] == "pending" and tx[0]["tx_id"] == t["id"]


async def test_topup_rates_and_validation(login):
    u = await login(1015)
    t = await new_topup(u, units=5000)
    assert t["uzs_amount"] == 50_000  # 5 000 ABU F = 50 000 UZS
    r = await u.post("/api/topup", json={"currency": "ABU_F", "provider": "mock", "idempotency_key": uuid.uuid4().hex, "units": 4})
    assert r.status_code == 400  # minimal 5 ABU F
    opts = (await u.get("/api/topup/options")).json()
    pk = next(p for p in opts["abu_ton_packages"] if p["units"] == 200)
    assert pk["price_uzs"] == 50_000
    t2 = await new_topup(u, currency="ABU_TON", package_id=pk["id"], units=None)
    assert t2["units"] == 200 and t2["uzs_amount"] == 50_000


async def test_old_topup_keeps_old_rate_after_admin_change(login, admin):
    u = await login(1016)
    t = await new_topup(u, units=100)
    assert (await admin.put("/api/admin/settings/abu_f_uzs_per_unit", {"value": 20})).status_code == 200
    t2 = await new_topup(u, units=100)
    assert t["uzs_amount"] == 1000 and t2["uzs_amount"] == 2000
    mine = {x["id"]: x for x in (await u.get("/api/topups")).json()}
    assert mine[t["id"]]["uzs_amount"] == 1000


async def test_unconfigured_provider_is_not_configured(login):
    u = await login(1017)
    r = await u.post("/api/topup", json={"currency": "ABU_F", "provider": "click", "idempotency_key": uuid.uuid4().hex, "units": 10})
    assert r.status_code == 409 and r.json()["error"]["code"] == "provider_not_configured"


async def test_topup_idempotency_key(login):
    u = await login(1018)
    body = {"currency": "ABU_F", "provider": "mock", "idempotency_key": "idem-key-1", "units": 10}
    a, b = await u.post("/api/topup", json=body), await u.post("/api/topup", json=body)
    assert a.json()["topup"]["id"] == b.json()["topup"]["id"]


async def test_manual_approve_only_once(login, admin):
    u = await login(1020)
    t = await new_topup(u, provider="manual_card", units=100)
    # chek yuklash balansni AVTOMATIK oshirmaydi
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
    r = await u.c.post(f"/api/topup/{t['id']}/receipt", headers=u.h, files={"file": ("c.png", png, "image/png")})
    assert r.status_code == 200 and r.json()["status"] == "awaiting_review"
    assert await u.balance() == 0
    internal = next(x for x in (await admin.get("/api/admin/topups")).json() if x["id"] == t["id"])["internal_id"]
    rs = await asyncio.gather(*[admin.post(f"/api/admin/topups/{internal}/review", {"approve": True}) for _ in range(3)])
    assert sorted(r.status_code for r in rs) == [200, 409, 409]
    assert await u.balance() == 100
    audits = (await admin.get("/api/admin/audit?action=topup.approve")).json()
    assert len(audits) == 1


async def test_admin_cannot_approve_provider_payment(login, admin):
    u = await login(1021)
    t = await new_topup(u, provider="mock")
    internal = next(x for x in (await admin.get("/api/admin/topups")).json() if x["id"] == t["id"])["internal_id"]
    assert (await admin.post(f"/api/admin/topups/{internal}/review", {"approve": True})).status_code == 403
    assert await u.balance() == 0


async def test_receipt_rejects_non_image(login):
    u = await login(1022)
    t = await new_topup(u, provider="manual_card")
    r = await u.c.post(f"/api/topup/{t['id']}/receipt", headers=u.h, files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert r.status_code == 415


async def test_stars_event_processing(login, monkeypatch):
    monkeypatch.setattr("app.config.settings.stars_enabled", True)
    async def fake_invoice(t):
        return f"https://t.me/$fake/{t.public_id}"
    monkeypatch.setattr("app.bot.instance.create_stars_invoice", fake_invoice)
    from app.db import SessionLocal
    from app.providers.base import PaymentEvent
    from app.services import topup as svc
    u = await login(1023)
    t = await new_topup(u, provider="stars", units=1000)  # 10 000 UZS -> 42 Stars
    from sqlalchemy import select
    from app.models import TopUp
    async with SessionLocal() as s:
        row = (await s.execute(select(TopUp).where(TopUp.public_id == t["id"]))).scalar_one()
        stars = row.stars_amount
    assert stars == 42
    async with SessionLocal() as s, s.begin():
        bad = PaymentEvent("c1", t["id"], "success", stars + 1, "XTR")
        with pytest.raises(Exception):
            await svc.process_event(s, "stars", bad)
    for _ in range(2):
        async with SessionLocal() as s, s.begin():
            await svc.process_event(s, "stars", PaymentEvent("charge-1", t["id"], "success", stars, "XTR"))
    assert await u.balance() == 1000


async def test_transactions_filter_and_detail(login):
    u = await login(1030)
    uid = await user_id_of(u.abu_id)
    await credit(uid, "ABU_F", 10)
    items = (await u.get("/api/me/transactions?type=bonus")).json()["items"]
    assert len(items) == 1 and items[0]["currency"] == "ABU_F"
    d = (await u.get(f"/api/me/transactions/{items[0]['tx_id']}")).json()
    assert d["receipt"]["valid"] is True
    other = await login(1031)
    assert (await other.get(f"/api/me/transactions/{items[0]['tx_id']}")).status_code == 404  # boshqa odamning chekini ko'rib bo'lmaydi
