import asyncio
import os
import subprocess
import sys
import time
import uuid

import pytest

from conftest import ROOT, TEST_DB, fund, init_data, user_id_of

K = lambda: uuid.uuid4().hex


# ------------------------------------------------------------------ initData
def test_init_data_verification():
    from app.errors import DomainError
    from app.security import verify_init_data
    ok = verify_init_data(init_data(77, "Ali"), "123456:TEST_TOKEN")
    assert ok["user"]["id"] == 77
    for bad in (init_data(77, tamper=True), init_data(77, token="999:OTHER"), init_data(77, auth_date=int(time.time()) - 10 * 86400), "", "hash=abc"):
        with pytest.raises(DomainError):
            verify_init_data(bad, "123456:TEST_TOKEN")


async def test_auth_rejects_forged_init_data(client):
    r = await client.post("/api/auth/telegram", json={"init_data": init_data(5, tamper=True)})
    assert r.status_code == 401
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me", headers={"Authorization": "Bearer abc.def"})).status_code == 401


async def test_public_abu_id_independent_of_telegram_id(login):
    u = await login(424242)
    assert "424242" not in u.abu_id and u.abu_id.startswith("ABU-")
    assert "telegram_id" not in u.me


async def test_banned_user_blocked(login, admin):
    u = await login(4001)
    assert (await admin.post(f"/api/admin/users/{u.abu_id}/ban", {"banned": True, "reason": "test"})).status_code == 200
    assert (await u.get("/api/me")).status_code == 403
    await admin.post(f"/api/admin/users/{u.abu_id}/ban", {"banned": False})
    assert (await u.get("/api/me")).status_code == 200


# ------------------------------------------------------------------ admin ruxsatlari
ADMIN_ENDPOINTS = [("get", "/api/admin/dashboard"), ("get", "/api/admin/users"), ("get", "/api/admin/topups"), ("get", "/api/admin/orders"),
                   ("get", "/api/admin/audit"), ("get", "/api/admin/settings"), ("get", "/api/admin/promo"), ("get", "/api/admin/roles"),
                   ("post", "/api/admin/products"), ("put", "/api/admin/settings/uzs_per_star")]


async def test_non_admin_cannot_use_admin_api(login, client):
    u = await login(4010)
    for method, url in ADMIN_ENDPOINTS:
        r = await getattr(u, method)(url, **({"json": {"value": 1}} if method in ("post", "put") else {}))
        assert r.status_code == 403, (url, r.status_code)
        r = await client.request(method.upper(), url)  # tokensiz
        assert r.status_code == 401, url
    assert (await u.get("/api/me")).json()["is_admin"] is False


async def test_admin_bootstrap_only_from_env_and_granular_roles(login, admin):
    assert admin.me["is_admin"] is True
    mod = await login(4011)
    assert (await admin.post("/api/admin/admins", {"abu_id": mod.abu_id, "role": "moderator"})).status_code == 200
    assert (await mod.get("/api/admin/users")).status_code == 200  # moderator: users.view bor
    for method, url in [("get", "/api/admin/audit"), ("get", "/api/admin/topups"), ("get", "/api/admin/roles")]:
        assert (await getattr(mod, method)(url)).status_code == 403, url
    r = await mod.post(f"/api/admin/users/{admin.abu_id}/adjust", {"currency": "ABU_F", "amount": 5, "reason": "xxxxxx", "idempotency_key": K()})
    assert r.status_code == 403
    fin = await login(4012)
    await admin.post("/api/admin/admins", {"abu_id": fin.abu_id, "role": "finance-view"})
    assert (await fin.get("/api/admin/topups")).status_code == 200
    assert (await fin.post("/api/admin/topups/1/review", {"approve": True})).status_code == 403  # faqat ko'rish
    await admin.post("/api/admin/admins", {"abu_id": mod.abu_id, "role": None})
    assert (await mod.get("/api/admin/users")).status_code == 403  # huquq darhol olinadi (token emas, DB tekshiriladi)


async def test_admin_adjust_needs_reason_and_is_audited(login, admin):
    u = await login(4020)
    bad = await admin.post(f"/api/admin/users/{u.abu_id}/adjust", {"currency": "ABU_F", "amount": 50, "reason": "x", "idempotency_key": K()})
    assert bad.status_code == 422
    key = K()
    body = {"currency": "ABU_TON", "amount": 9, "reason": "Kompensatsiya testi", "idempotency_key": key}
    assert (await admin.post(f"/api/admin/users/{u.abu_id}/adjust", body)).status_code == 200
    assert (await admin.post(f"/api/admin/users/{u.abu_id}/adjust", body)).status_code == 200  # takror - qo'shilmaydi
    assert await u.balance("ABU_TON") == 9 and await u.balance("ABU_F") == 0
    assert (await admin.post(f"/api/admin/users/{u.abu_id}/adjust", {**body, "amount": -50, "idempotency_key": K()})).status_code == 402
    log = (await admin.get("/api/admin/audit?action=balance.adjust")).json()
    assert len(log) == 1 and log[0]["detail"]["reason"] == "Kompensatsiya testi"


async def test_media_upload_validated_by_magic_bytes(login, admin):
    p = (await admin.post("/api/admin/products", {"category_id": 1, "title": "M", "price_uzs": 1})).json()
    up = lambda name, data: admin.c.post("/api/admin/media", headers=admin.h, data={"product_id": str(p["id"])}, files={"file": (name, data, "image/png")})
    assert (await up("a.png", b"<svg onload=alert(1)>")).status_code == 415
    assert (await up("a.png", b"\x89PNG\r\n\x1a\n" + b"1" * 20)).status_code == 200
    assert (await up("big.png", b"\x89PNG\r\n\x1a\n" + b"1" * 3_000_000)).status_code == 413
    m = (await admin.get(f"/api/admin/media?product_id={p['id']}")).json()[0]
    r = await admin.c.get(m["url"])
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------------------------ market (ichki escrow)
async def listing(admin, seller, **kw):
    body = {"category": "stars", "title": "100 Stars", "price_amount": 1000, "price_currency": "ABU_F", "quantity": 3, **kw}
    r = await seller.post("/api/market/listings", body)
    assert r.status_code == 200, r.text
    li = r.json()
    assert li["status"] == "pending"  # moderatsiyasiz ko'rinmaydi
    assert (await seller.get("/api/market/listings")).json() == []
    assert (await admin.post(f"/api/admin/listings/{li['id']}/moderate", {"status": "active"})).status_code == 200
    return li


async def test_market_escrow_confirm_flow_with_commission(login, admin):
    s, b = await login(4030), await login(4031)
    li = await listing(admin, s)
    await fund(b, "ABU_F", 5000)
    key = K()
    r = await b.post(f"/api/market/listings/{li['id']}/buy", {"qty": 2, "idempotency_key": key})
    assert r.status_code == 200 and r.json()["amount"] == 2000
    assert (await b.post(f"/api/market/listings/{li['id']}/buy", {"qty": 2, "idempotency_key": key})).json()["id"] == r.json()["id"]
    oid = r.json()["id"]
    assert await b.balance() == 3000 and await s.balance() == 0  # pul escrow'da
    assert (await b.post(f"/api/market/orders/{oid}/deliver")).status_code == 403  # faqat sotuvchi
    assert (await s.post(f"/api/market/orders/{oid}/deliver")).status_code == 200
    assert (await s.post(f"/api/market/orders/{oid}/confirm")).status_code == 403  # sotuvchi o'zi tasdiqlay olmaydi
    assert (await b.post(f"/api/market/orders/{oid}/confirm")).status_code == 200
    assert (await b.post(f"/api/market/orders/{oid}/confirm")).status_code == 409
    assert await s.balance() == 1900 and await b.balance() == 3000  # 5% komissiya
    assert (await b.post(f"/api/market/orders/{oid}/review", {"rating": 4, "text": "ok"})).status_code == 200
    assert (await b.post(f"/api/market/orders/{oid}/review", {"rating": 4})).status_code == 409
    page = (await b.get(f"/api/market/seller/{s.abu_id}")).json()
    assert page["seller"]["rating"] == 4.0 and page["seller"]["sales"] == 1


async def test_market_dispute_refund_and_rules(login, admin):
    s, b = await login(4040), await login(4041)
    li = await listing(admin, s, quantity=1)
    await fund(b, "ABU_F", 5000)
    assert (await s.post(f"/api/market/listings/{li['id']}/buy", {"qty": 1, "idempotency_key": K()})).status_code == 400  # o'z e'loni
    oid = (await b.post(f"/api/market/listings/{li['id']}/buy", {"qty": 1, "idempotency_key": K()})).json()["id"]
    assert (await b.post(f"/api/market/listings/{li['id']}/buy", {"qty": 1, "idempotency_key": K()})).status_code == 404  # sotilib bo'ldi
    d = await b.post(f"/api/market/orders/{oid}/dispute", {"reason": "Tovar kelmadi"})
    assert d.status_code == 200
    assert (await b.post(f"/api/market/orders/{oid}/confirm")).status_code == 409  # nizo paytida tasdiqlab bo'lmaydi
    res = await admin.post(f"/api/admin/disputes/{d.json()['dispute_id']}/resolve", {"decision": "refund_buyer", "note": "isbot"})
    assert res.status_code == 200 and await b.balance() == 5000 and await s.balance() == 0
    assert (await admin.post(f"/api/admin/disputes/{d.json()['dispute_id']}/resolve", {"decision": "release_to_seller"})).status_code == 409
    assert (await s.get(f"/api/market/my/listings")).json()[0]["status"] == "active"  # miqdor qaytdi


async def test_market_parallel_buys_do_not_oversell(login, admin):
    s = await login(4050)
    li = await listing(admin, s, quantity=1)
    buyers = [await login(4051 + i) for i in range(4)]
    for x in buyers:
        await fund(x, "ABU_F", 3000)
    rs = await asyncio.gather(*[x.post(f"/api/market/listings/{li['id']}/buy", {"qty": 1, "idempotency_key": K()}) for x in buyers])
    assert sorted(r.status_code for r in rs).count(200) == 1
    assert sorted([await x.balance() for x in buyers]) == [2000, 3000, 3000, 3000]


async def test_market_edit_resets_moderation_and_validation(login, admin):
    s = await login(4060)
    li = await listing(admin, s)
    assert (await s.patch(f"/api/market/listings/{li['id']}", {"price_amount": 1500})).json()["status"] == "pending"
    bad = await s.post("/api/market/listings", {"category": "weapons", "title": "x", "price_amount": 1, "price_currency": "ABU_F"})
    assert bad.status_code == 400
    assert (await s.post("/api/market/listings", {"category": "stars", "title": "abc", "price_amount": 1, "price_currency": "UZS"})).status_code == 400


# ------------------------------------------------------------------ infra
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_telegram_webhook_requires_secret(client):
    assert (await client.post("/api/telegram/webhook/wrong", json={})).status_code == 403


def test_alembic_migration_on_clean_database():
    import asyncio as aio
    import asyncpg
    dsn = TEST_DB.replace("postgresql+asyncpg://", "postgresql://")
    base, _ = dsn.rsplit("/", 1)
    name = "abu_bot_mig_" + uuid.uuid4().hex[:6]

    async def run(sql):
        c = await asyncpg.connect(base + "/abu_bot_test")
        try:
            await c.execute(sql)
        finally:
            await c.close()
    aio.run(run(f"CREATE DATABASE {name}"))
    try:
        env = dict(os.environ, DATABASE_URL=f"{base.replace('postgresql://', 'postgresql+asyncpg://')}/{name}")
        up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
        assert up.returncode == 0, up.stderr[-1500:]
        down = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=ROOT, env=env, capture_output=True, text=True)
        assert down.returncode == 0, down.stderr[-1500:]
        again = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
        assert again.returncode == 0
    finally:
        aio.run(run(f"DROP DATABASE {name} WITH (FORCE)"))


def test_models_match_migration():
    """Alembic autogenerate qo'shimcha o'zgarish topmasligi kerak (model va migratsiya bir xil)."""
    env = dict(os.environ, DATABASE_URL=TEST_DB)
    r = subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
