import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import scheduler
from .bot import instance as botmod
from .config import settings
from .db import SessionLocal, engine
from .errors import DomainError
from .routers import admin, market, shop, social, user, webhooks
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("abu")
ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist"
ASSETS = ROOT / "assets"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_prod and settings.secret_key.startswith("dev"):
        raise RuntimeError("Prod muhitida SECRET_KEY o'zgartirilishi shart")
    if settings.env != "test":
        async with SessionLocal() as s, s.begin():
            await seed(s)
    bot = botmod.init_bot()
    if bot and settings.env != "test":
        try:
            await botmod.setup_menu_button()
            if settings.webapp_url and settings.webhook_secret:
                await bot.set_webhook(f"{settings.webapp_url}/api/telegram/webhook/{settings.webhook_secret}", secret_token=settings.webhook_secret,
                                      allowed_updates=["message", "callback_query", "pre_checkout_query"])
        except Exception as ex:
            log.warning("Bot sozlash xatosi: %s", ex)
    if settings.run_scheduler and settings.env != "test":
        scheduler.start()
    yield
    scheduler.stop()
    if botmod.bot:
        await botmod.bot.session.close()
    await engine.dispose()


app = FastAPI(title="ABU BOT", lifespan=lifespan, docs_url=None if settings.is_prod else "/docs", redoc_url=None)
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")], allow_methods=["*"], allow_headers=["*"])

_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Oddiy tezlik cheklovi (jarayon ichida; ko'p instansda Redis kerak) + xavfsizlik sarlavhalari."""
    if request.url.path.startswith("/api/") and settings.env != "test":
        key = (request.headers.get("authorization") or "")[-24:] or (request.client.host if request.client else "?")
        q, now = _hits[key], time.monotonic()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.rate_limit_per_minute:
            return JSONResponse({"error": {"code": "rate_limited", "message": "Juda ko'p so'rov"}}, status_code=429)
        q.append(now)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.exception_handler(DomainError)
async def domain_error(_, e: DomainError):
    return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=e.status)


@app.exception_handler(RequestValidationError)
async def validation_error(_, e: RequestValidationError):
    return JSONResponse({"error": {"code": "validation", "message": "So'rov ma'lumotlari noto'g'ri", "detail": [x["loc"][-1] for x in e.errors()]}}, status_code=422)


@app.get("/health")
async def health():
    async with engine.connect() as c:
        await c.execute(text("select 1"))
    return {"status": "ok", "bot": bool(settings.bot_token)}


@app.post("/api/telegram/webhook/{secret}")
async def tg_webhook(secret: str, request: Request):
    import hmac
    if not settings.webhook_secret or not hmac.compare_digest(secret, settings.webhook_secret) or \
            not hmac.compare_digest(request.headers.get("x-telegram-bot-api-secret-token", ""), settings.webhook_secret) or botmod.bot is None:
        return JSONResponse({"ok": False}, status_code=403)
    await botmod.dp.feed_update(botmod.bot, Update.model_validate(await request.json(), context={"bot": botmod.bot}))
    return {"ok": True}


for r in (user.router, shop.router, market.router, social.router, admin.router, webhooks.router):
    app.include_router(r)

if ASSETS.exists():
    app.mount("/assets-static", StaticFiles(directory=ASSETS), name="abu-assets")
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "Topilmadi"}}, status_code=404)
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
