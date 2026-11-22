import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid
from urllib.parse import urlencode

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://abu:abu_dev_pass@localhost:5432/abu_bot_test")
os.environ.update(ENV="test", DATABASE_URL=TEST_DB, BOT_TOKEN="123456:TEST_TOKEN", SECRET_KEY="test-secret", MOCK_PROVIDER_ENABLED="true",
                  MOCK_WEBHOOK_SECRET="whsec", MANUAL_CARD_INFO="Test karta: 0000 (faqat test)", ADMIN_TELEGRAM_IDS="900001", RUN_SCHEDULER="false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Test bazasini Alembic bilan yaratamiz (shu bilan migratsiya ham sinaladi)."""
    env = dict(os.environ, DATABASE_URL=TEST_DB)
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=ROOT, env=env, check=False, capture_output=True)
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]


@pytest_asyncio.fixture(autouse=True)
async def clean(migrated_db):
    from app.db import SessionLocal, engine
    from app.models import Base
    from app.seed import seed
    async with engine.begin() as c:
        names = ",".join(t.name for t in Base.metadata.sorted_tables)
        await c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    async with SessionLocal() as s, s.begin():
        await seed(s)
    from app.services import channels
    channels.set_member_checker(None)
    yield


@pytest_asyncio.fixture
async def client():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def init_data(tg_id: int, name="Test", start_param=None, auth_date=None, token="123456:TEST_TOKEN", tamper=False) -> str:
    user = json.dumps({"id": tg_id, "first_name": name, "username": f"u{tg_id}"}, separators=(",", ":"))
    d = {"auth_date": str(auth_date or int(time.time())), "user": user, "query_id": "AA"}
    if start_param:
        d["start_param"] = start_param
    check = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        d["user"] = d["user"].replace(str(tg_id), str(tg_id + 1))
    return urlencode(d)


class Actor:
    def __init__(self, client, tg_id, token, me):
        self.c, self.tg_id, self.me = client, tg_id, me
        self.h = {"Authorization": f"Bearer {token}"}
        self.abu_id = me["abu_id"]

    async def get(self, url, **kw):
        return await self.c.get(url, headers=self.h, **kw)

    async def post(self, url, json=None, **kw):
        return await self.c.post(url, headers=self.h, json=json, **kw)

    async def patch(self, url, json=None):
        return await self.c.patch(url, headers=self.h, json=json)

    async def put(self, url, json=None):
        return await self.c.put(url, headers=self.h, json=json)

    async def balance(self, cur="ABU_F"):
        return (await self.get("/api/me")).json()["balances"][cur]["balance"]


@pytest.fixture
def login(client):
    async def _login(tg_id: int, start_param=None) -> Actor:
        r = await client.post("/api/auth/telegram", json={"init_data": init_data(tg_id, f"User{tg_id}", start_param)})
        assert r.status_code == 200, r.text
        return Actor(client, tg_id, r.json()["token"], r.json()["me"])
    return _login


@pytest_asyncio.fixture
async def admin(login):
    return await login(900001)  # ADMIN_TELEGRAM_IDS -> superadmin


async def credit(user_id: int, currency: str, amount: int, key: str | None = None):
    from app.db import SessionLocal
    from app.services import ledger
    async with SessionLocal() as s, s.begin():
        await ledger.post_entry(s, user_id=user_id, currency=currency, amount=amount, kind="bonus_promo", idem=key or f"t:{uuid.uuid4()}")


async def user_id_of(abu_id: str) -> int:
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import User
    async with SessionLocal() as s:
        return (await s.execute(select(User.id).where(User.abu_id == abu_id))).scalar_one()


async def fund(actor: Actor, currency="ABU_F", amount=100_000):
    await credit(await user_id_of(actor.abu_id), currency, amount)


def sign(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    return raw, {"X-Signature": hmac.new(b"whsec", raw, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}
