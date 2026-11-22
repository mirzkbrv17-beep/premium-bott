"""Aiogram bot: /start, referral deep-link, obuna tekshiruvi, Mini App tugmasi, Stars to'lovlari, /admin."""
import logging
import uuid
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, MenuButtonWebApp, Message,
                           PreCheckoutQuery, WebAppInfo)
from sqlalchemy import select

from ..config import settings
from ..errors import DomainError as _DE
from ..models import TopUp as _TopUp, AdminUser, Permission, RolePermission
from ..db import SessionLocal
from ..errors import DomainError
from ..models import AdminUser, TopUp, User
from ..providers.base import PaymentEvent
from ..security import create_token
from ..services import channels, settings_svc, topup as topup_svc, users as users_svc

log = logging.getLogger("abu.bot")
bot: Optional[Bot] = None
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Haqiqiy custom_emoji_id bo'lmasa oddiy emoji ishlatiladi (soxta ID yasalmaydi). Admin AppSetting 'custom_emoji' orqali beradi.
_CUSTOM: dict[str, str] = {}


def e(name: str, fallback: str) -> str:
    cid = _CUSTOM.get(name)
    return f'<tg-emoji emoji-id="{cid}">{fallback}</tg-emoji>' if cid else fallback


def init_bot() -> Optional[Bot]:
    global bot
    if settings.bot_token and bot is None:
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        channels.set_member_checker(_member_checker)
    return bot


async def _member_checker(chat_id: str, telegram_id: int) -> Optional[bool]:
    if bot is None:
        return None
    try:
        m = await bot.get_chat_member(chat_id, telegram_id)
    except Exception as ex:  # bot kanalda admin emas / kanal topilmadi -> tekshirib bo'lmaydi
        log.warning("get_chat_member xatosi %s: %s", chat_id, ex)
        return None
    return m.status in ("creator", "administrator", "member") or (m.status == "restricted" and getattr(m, "is_member", False))


def webapp_kb(text="🚀 ABU BOT ochish") -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.webapp_url))]])


async def setup_menu_button() -> None:
    if bot and settings.webapp_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="ABU BOT", web_app=WebAppInfo(url=settings.webapp_url)))


async def _sub_message(session, tg_id: int):
    r = await channels.check_subscription(session, tg_id)
    if r["ok"] or r["unverifiable"]:
        return None
    rows = [[InlineKeyboardButton(text=f"📢 {c['title']}", url=c["url"])] for c in map(channels.channel_dict, r["missing"]) if c["url"]]
    rows.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("start"))
async def cmd_start(m: Message, command: CommandObject):
    async with SessionLocal() as s:
        user, created = await users_svc.get_or_create_telegram_user(s, {"id": m.from_user.id, "first_name": m.from_user.first_name, "last_name": m.from_user.last_name,
                                                                         "username": m.from_user.username, "language_code": m.from_user.language_code, "is_bot": m.from_user.is_bot}, command.args)
        kb = await _sub_message(s, m.from_user.id)
        await s.commit()
    if kb:
        await m.answer(f"{e('mega', '📢')} <b>Majburiy obuna</b>\nABU BOT'dan foydalanish uchun quyidagi kanal(lar)ga obuna bo'ling va «Obunani tekshirish» tugmasini bosing:", reply_markup=kb)
        return
    await m.answer(f"{e('gift', '🎁')} <b>ABU BOT</b>ga xush kelibsiz, {m.from_user.first_name}!\nDo'kon, ijara, market va kabinet - hammasi bitta Mini App'da.",
                   reply_markup=webapp_kb() or None)


@router.callback_query(F.data == "check_sub")
async def cb_check(c: CallbackQuery):
    async with SessionLocal() as s:
        kb = await _sub_message(s, c.from_user.id)
    if kb:
        await c.answer("Hali obuna to'liq emas", show_alert=True)
        return
    await c.message.answer(f"{e('ok', '✅')} <b>Obuna tasdiqlandi!</b>", reply_markup=webapp_kb())
    await c.answer()


@router.message(Command("help"))
async def cmd_help(m: Message):
    sup = f"\nAloqa: {settings.support_username}" if settings.support_username else ""
    await m.answer("ℹ️ /start - boshlash\n/help - yordam\nBarcha amallar Mini App ichida: do'kon, ijara, market, balans va support." + sup, reply_markup=webapp_kb())


@router.message(Command("admin"))
async def cmd_admin(m: Message):
    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.telegram_id == m.from_user.id))).scalar_one_or_none()
        if user is None:
            return
        await users_svc._bootstrap_admin(s, user)
        adm = (await s.execute(select(AdminUser).where(AdminUser.user_id == user.id, AdminUser.active.is_(True)))).scalar_one_or_none()
        await s.commit()
    if not adm:
        return  # ruxsatsizga javob ham berilmaydi
    if not settings.webapp_url:
        await m.answer("WEBAPP_URL sozlanmagan.")
        return
    tok = create_token({"uid": user.id, "jti": uuid.uuid4().hex}, ttl=300, purpose="admin_link")
    await m.answer("🔐 Admin panel (havola 5 daqiqa amal qiladi, bir marta ishlaydi):",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Admin panelni ochish", url=f"{settings.webapp_url}/#/admin-login/{tok}")]]))


# ------------------------------------------------------------------ Telegram Stars (XTR)
async def create_stars_invoice(t: TopUp) -> Optional[str]:
    if bot is None or not t.stars_amount:
        return None
    return await bot.create_invoice_link(title=f"{t.units} {t.currency.replace('_', ' ')}", description="ABU BOT balansini to'ldirish",
                                         payload=t.public_id, currency="XTR", prices=[LabeledPrice(label=t.currency.replace('_', ' '), amount=t.stars_amount)],
                                         provider_token="")


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    async with SessionLocal() as s:
        t = (await s.execute(select(TopUp).where(TopUp.public_id == q.invoice_payload))).scalar_one_or_none()
        u = (await s.execute(select(User).where(User.telegram_id == q.from_user.id))).scalar_one_or_none()
        ok = bool(t and u and t.user_id == u.id and t.provider == "stars" and t.status == "pending" and q.currency == "XTR" and q.total_amount == t.stars_amount)
    await q.answer(ok=ok, error_message=None if ok else "To'lov ma'lumoti mos emas")


@router.message(F.successful_payment)
async def paid(m: Message):
    sp = m.successful_payment
    async with SessionLocal() as s:
        try:
            await topup_svc.process_event(s, "stars", PaymentEvent(event_id=sp.telegram_payment_charge_id, topup_public_id=sp.invoice_payload, status="success",
                                                                    paid_amount=sp.total_amount, paid_unit=sp.currency, external_id=sp.telegram_payment_charge_id))
            await s.commit()
        except DomainError as ex:
            await s.rollback()
            log.error("Stars to'lov rad etildi: %s", ex.message)
            return
    await m.answer(f"{e('ok', '✅')} To'lov qabul qilindi, balans yangilandi.")


async def send_text(telegram_id: int, text: str) -> bool:
    if bot is None:
        return False
    try:
        await bot.send_message(telegram_id, text, reply_markup=webapp_kb("Ochish"))
        return True
    except Exception as ex:
        log.info("yuborilmadi %s: %s", telegram_id, ex)
        return False


# ------------------------------------------------------------------ karta to'lovi: chek -> admin tasdiqlaydi
async def _admin_with_perm(session, tg_id: int, code: str):
    u = (await session.execute(select(User).where(User.telegram_id == tg_id))).scalar_one_or_none()
    if u is None:
        return None
    adm = (await session.execute(select(AdminUser).where(AdminUser.user_id == u.id, AdminUser.active.is_(True)))).scalar_one_or_none()
    if adm is None:
        return None
    if adm.role.name == "superadmin":
        return u
    codes = (await session.execute(select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id)
                                   .where(RolePermission.role_id == adm.role_id))).scalars().all()
    return u if code in codes else None


@router.message(F.photo, F.chat.type == "private")
async def on_receipt(m: Message):
    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.telegram_id == m.from_user.id))).scalar_one_or_none()
        if user is None:
            await m.answer("Avval /start bosing.")
            return
        t = (await s.execute(select(_TopUp).where(_TopUp.user_id == user.id, _TopUp.provider == "manual_card",
                                                   _TopUp.status.in_(["pending", "awaiting_review"]))
                             .order_by(_TopUp.id.desc()).limit(1).with_for_update())).scalar_one_or_none()
        if t is None:
            await m.answer("Faol karta to'lovi topilmadi. Avval Balans → To‘ldirish bo‘limida summani tanlang.")
            return
        t.details = {**(t.details or {}), "tg_file_id": m.photo[-1].file_id}
        t.status = "awaiting_review"
        await s.commit()
        caption = (f"💳 Yangi chek\nFoydalanuvchi: {user.first_name} ({user.abu_id})\n"
                   f"Miqdor: {t.units} {t.currency.replace('_', ' ')}\nSo‘m: {t.uzs_amount:,}".replace(",", " ")
                   + f"\nID: {t.public_id}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"tp:ok:{t.public_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"tp:no:{t.public_id}")]])
        fid = m.photo[-1].file_id
    sent = 0
    for aid in settings.admin_ids:
        try:
            await bot.send_photo(aid, fid, caption=caption, reply_markup=kb)
            sent += 1
        except Exception as ex:
            log.warning("admin %s ga chek yuborilmadi: %s", aid, ex)
    if sent:
        await m.answer("✅ Chek qabul qilindi. Admin tekshirgach balansingizga qo‘shiladi.")
    else:
        await m.answer("Chek qabul qilindi, lekin admin hozir xabar ololmadi. Iltimos, keyinroq qayta yuboring yoki @mirzkbrv17 ga murojaat qiling.")


@router.callback_query(F.data.startswith("tp:"))
async def cb_review(c: CallbackQuery):
    try:
        _, action, pid = c.data.split(":", 2)
    except ValueError:
        await c.answer()
        return
    approve = action == "ok"
    async with SessionLocal() as s:
        admin = await _admin_with_perm(s, c.from_user.id, "payments.review")
        if admin is None:
            await c.answer("Sizda ruxsat yo'q", show_alert=True)
            return
        t = (await s.execute(select(_TopUp).where(_TopUp.public_id == pid))).scalar_one_or_none()
        if t is None:
            await c.answer("To'lov topilmadi", show_alert=True)
            return
        try:
            await topup_svc.admin_review(s, t.id, approve=approve, admin_id=admin.id,
                                         note=None if approve else "Chek tasdiqlanmadi")
            await s.commit()
        except _DE as ex:
            await s.rollback()
            await c.answer(ex.message, show_alert=True)
            return
    result = "✅ Tasdiqlandi" if approve else "❌ Rad etildi"
    who = f"@{c.from_user.username}" if c.from_user.username else str(c.from_user.id)
    try:
        await c.message.edit_caption(caption=f"{c.message.caption or ''}\n\n{result} ({who})", reply_markup=None)
    except Exception:
        try:
            await c.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await c.answer(result)
