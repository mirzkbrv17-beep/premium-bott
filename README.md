# ABU BOT

Telegram bot + Mini App: ABU SHOP (do'kon), ABU RENT (ijara), ABU NFT, ABU MARKET (escrow), ABU GIFT, bonuslar, VIP, admin panel.
Stack: FastAPI · aiogram 3 · SQLAlchemy 2 (async) · Alembic · PostgreSQL · React + TypeScript + Vite.

## Asosiy qoidalar (xavfsizlik va pul)
- Balans faqat `ledger_entries` orqali o'zgaradi: o'zgarmas yozuvlar (ORM va PostgreSQL trigger himoyasi), idempotency kaliti, hisob qatori `FOR UPDATE`, manfiy balans yo'q.
- ABU F / ABU TON pulga aylantirilmaydi; haqiqiy to'lov provayder webhook'i (imzo + summa/valyuta tekshiruvi) yoki admin tasdig'i orqali.
- Telegram initData HMAC bilan serverda tekshiriladi; admin huquqi har so'rovda DB'dan olinadi.
- Majburiy obuna, referral mukofoti, vazifa mukofoti serverda qayta tekshiriladi.
- Fayllar magic-bytes bo'yicha tekshiriladi; SVG yuklanmaydi.

## Ishga tushirish (lokal)
```bash
# 1) PostgreSQL + Python 3.12
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cp .env.example .env            # qiymatlarni to'ldiring
export DATABASE_URL=postgresql+asyncpg://abu:abu_dev_pass@localhost:5432/abu_bot
alembic upgrade head
# 2) Backend
uvicorn main:app --reload --port 8000
# 3) Frontend (alohida terminal)
cd frontend && npm install && npm run dev        # http://localhost:5173 (/api proxy)
# ixtiyoriy demo ma'lumot (faqat dev):
cd backend && python -m app.seed_demo
```

## Testlar
```bash
TEST_DATABASE_URL=postgresql+asyncpg://abu:abu_dev_pass@localhost:5432/abu_bot_test python -m pytest tests -q
cd frontend && npm run typecheck && npm run build
```
Testlar haqiqiy PostgreSQL'da ishlaydi (parallel so'rovlar, qulflar, trigger, migratsiya ham sinaladi).

## Deploy (Render)
`render.yaml` Docker + PostgreSQL'ni yaratadi. Env: `BOT_TOKEN`, `WEBAPP_URL`, `ADMIN_TELEGRAM_IDS`, `MANUAL_CARD_INFO`.
Bot webhook'i ilova startida `WEBAPP_URL/api/telegram/webhook/<WEBHOOK_SECRET>` ga o'rnatiladi.

## To'lov usullari — holat
| Usul | Holat |
|---|---|
| Telegram Stars | Bot token bilan ishlaydi (invoice + pre_checkout + successful_payment) |
| Karta (qo'lda tasdiq) | `MANUAL_CARD_INFO` berilsa; chek yuklanadi, admin tasdiqlaydi |
| Click | Prepare/Complete adapteri yozilgan, imzo formulasi Click hujjatiga muvofiq. **Haqiqiy merchant/sandbox hisobsiz sinalmagan** — `CLICK_*` berilmaguncha "sozlanmagan" ko'rinadi |
| Mock | Faqat `ENV!=prod` va `MOCK_PROVIDER_ENABLED=true` |

Soxta to'lov yoki soxta mahsulot yaratilmaydi: `not_configured` holatlari aniq ko'rsatiladi.

## Ma'lum cheklovlar
- Rate limit jarayon ichida (ko'p instansda Redis kerak).
- Telegram `custom_emoji` ID'lari (premium emoji) admin tomonidan kiritiladi; ID o'ylab topilmaydi.
- Mahsulot tafsiloti to'g'ridan-to'g'ri havola bilan ochilganda ro'yxatga qaytadi.
