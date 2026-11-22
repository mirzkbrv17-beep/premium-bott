"""Kabinet: profil, balans, tranzaksiyalar, to'ldirish, bonus, referral, promo, VIP, vazifalar, support..."""
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..errors import DomainError, not_found
from ..models import (Achievement, AdminUser, LedgerEntry, News, Notification, Referral, SupportMessage, SupportTicket,
                      Task, TopUp, User, UserAchievement, UserTask)
from ..security import create_token, verify_init_data
from ..serializers import topup_dict
from ..services import bonus, channels, ledger, settings_svc, social, topup as topup_svc, users as users_svc
from ..services.progress import check_achievements, level_of, vip_for
from ..timeutil import now_utc
from ..uploads import sniff_image

router = APIRouter(prefix="/api")

DEFAULT_SETTINGS = {"language": "uz", "animations": "auto", "hide_balance": False, "show_in_leaderboard": True,
                    "notifications": {"order": True, "rental": True, "payment": True, "bonus": True, "product": True, "promo": True, "referral": True, "market": True, "support": True}}


class TgAuth(BaseModel):
    init_data: str
    start_param: str | None = None


async def _me(session: AsyncSession, user: User) -> dict:
    bal = await ledger.balances(session, user.id)
    per = int(await settings_svc.get(session, "xp_per_level"))
    topped_uzs = await session.scalar(select(func.coalesce(func.sum(TopUp.uzs_amount), 0)).where(TopUp.user_id == user.id, TopUp.status == "success"))
    admin = (await session.execute(select(AdminUser).where(AdminUser.user_id == user.id, AdminUser.active.is_(True)))).scalar_one_or_none()
    s = {**DEFAULT_SETTINGS, **(user.profile.settings if user.profile else {})}
    return {"abu_id": user.abu_id, "first_name": user.first_name, "last_name": user.last_name, "username": user.username,
            "photo_url": user.photo_url, "created_at": user.created_at.isoformat(), "referral_code": user.referral_code,
            "level": level_of(user.xp, per), "vip": (await vip_for(session, user))["current"], "is_admin": admin is not None,
            "balances": bal, "uzs": {"topped_up": int(topped_uzs), "spent": user.spent_uzs_total}, "settings": s,
            "decoration": user.profile.decoration if user.profile else None,
            "bot_username": settings.bot_username}


@router.post("/auth/telegram")
async def auth_telegram(body: TgAuth, session: AsyncSession = Depends(get_session)):
    data = verify_init_data(body.init_data)  # imzo backendda tekshiriladi
    user, created = await users_svc.get_or_create_telegram_user(session, data["user"], body.start_param or data.get("start_param"))
    if user.is_banned:
        raise DomainError("banned", "Akkaunt cheklangan", 403)
    token = create_token({"uid": user.id}, ttl=12 * 3600)
    return {"token": token, "created": created, "me": await _me(session, user)}


class AdminLink(BaseModel):
    token: str


@router.post("/auth/admin-link")
async def auth_admin_link(body: AdminLink, session: AsyncSession = Depends(get_session)):
    """Bot /admin yuborgan bir martalik havola tokenini sessiyaga almashtiradi (desktop uchun)."""
    from ..models import UsedToken
    from ..security import read_token
    from sqlalchemy.exc import IntegrityError
    d = read_token(body.token, purpose="admin_link")
    try:
        async with session.begin_nested():
            session.add(UsedToken(jti=d["jti"]))
            await session.flush()
    except IntegrityError:
        raise DomainError("auth_failed", "Havola allaqachon ishlatilgan", 401)
    user = await session.get(User, int(d["uid"]))
    admin = (await session.execute(select(AdminUser).where(AdminUser.user_id == user.id, AdminUser.active.is_(True)))).scalar_one_or_none()
    if not admin:
        raise DomainError("forbidden", "Admin huquqi yo'q", 403)
    return {"token": create_token({"uid": user.id}, ttl=8 * 3600)}


@router.get("/me")
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _me(session, user)


class SettingsIn(BaseModel):
    language: str | None = Field(None, pattern="^(uz|ru|en)$")
    animations: str | None = Field(None, pattern="^(auto|on|off)$")
    hide_balance: bool | None = None
    show_in_leaderboard: bool | None = None
    notifications: dict[str, bool] | None = None


@router.patch("/me/settings")
async def patch_settings(body: SettingsIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    s = {**DEFAULT_SETTINGS, **(user.profile.settings or {})}
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "notifications":
            s["notifications"] = {**s["notifications"], **{kk: vv for kk, vv in v.items() if kk in DEFAULT_SETTINGS["notifications"]}}
        else:
            s[k] = v
    user.profile.settings = s
    return s


@router.get("/me/balance")
async def my_balance(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return (await _me(session, user))["balances"] | {"uzs": (await _me(session, user))["uzs"]}


# ------------------------------------------------------------------ tranzaksiyalar
KIND_GROUPS = {"topup": ["topup"], "spend": ["purchase", "rental", "market_hold", "market_promo", "gift_out"],
               "bonus": ["bonus_daily", "bonus_referral", "bonus_promo", "bonus_task"], "gift": ["gift_in", "gift_out", "gift_refund"],
               "refund": ["refund", "market_refund", "reversal"], "market": ["market_hold", "market_release", "commission", "market_promo"],
               "adjust": ["admin_adjust"]}
KIND_TITLES = {"topup": "Balans to'ldirish", "purchase": "Xarid", "rental": "Ijara", "refund": "Qaytarish", "bonus_daily": "Kunlik bonus",
               "bonus_referral": "Referral mukofoti", "bonus_promo": "Promo kod", "bonus_task": "Vazifa mukofoti", "gift_in": "Sovg'a qabul qilindi",
               "gift_out": "Sovg'a yuborildi", "gift_refund": "Sovg'a qaytarildi", "market_hold": "Market buyurtma", "market_release": "Market daromad",
               "market_refund": "Market qaytarish", "market_promo": "E'lon targ'iboti", "commission": "Komissiya", "admin_adjust": "Admin tuzatishi", "reversal": "Tuzatish"}


def _ledger_item(e: LedgerEntry) -> dict:
    return {"tx_id": e.tx_id, "kind": e.kind, "title": KIND_TITLES.get(e.kind, e.kind), "amount": e.amount, "currency": e.currency,
            "status": "success", "method": (e.meta or {}).get("provider") or "ABU balans", "credited_to": e.currency,
            "ts": e.created_at.isoformat(), "balance_after": e.balance_after, "ref": e.ref_id}


def _topup_item(t: TopUp) -> dict:
    return {"tx_id": t.public_id, "kind": "topup", "title": KIND_TITLES["topup"], "amount": t.units, "currency": t.currency, "status": t.status,
            "method": t.provider, "credited_to": t.currency, "ts": t.created_at.isoformat(), "uzs_amount": t.uzs_amount, "ref": t.public_id}


@router.get("/me/transactions")
async def my_transactions(type: str | None = None, status: str | None = None, date_from: str | None = None, date_to: str | None = None,
                          q: str | None = None, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                          user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    def parse(s, end=False):
        try:
            d = datetime.fromisoformat(s)
            return d + timedelta(days=1) if end and len(s) <= 10 else d
        except Exception:
            raise DomainError("bad_date", "Sana noto'g'ri")
    items: list[dict] = []
    lq = select(LedgerEntry).where(LedgerEntry.user_id == user.id)
    tq = select(TopUp).where(TopUp.user_id == user.id, TopUp.status != "success")
    if type:
        lq = lq.where(LedgerEntry.kind.in_(KIND_GROUPS.get(type, [type])))
    if date_from:
        lq, tq = lq.where(LedgerEntry.created_at >= parse(date_from)), tq.where(TopUp.created_at >= parse(date_from))
    if date_to:
        lq, tq = lq.where(LedgerEntry.created_at < parse(date_to, True)), tq.where(TopUp.created_at < parse(date_to, True))
    if q:
        lq, tq = lq.where(LedgerEntry.tx_id.ilike(f"%{q}%")), tq.where(TopUp.public_id.ilike(f"%{q}%"))
    if status in (None, "success"):
        items += [_ledger_item(e) for e in (await session.execute(lq.order_by(LedgerEntry.id.desc()).limit(page * size))).scalars()]
    if status != "success" and type in (None, "topup"):
        if status:
            tq = tq.where(TopUp.status == status)
        items += [_topup_item(t) for t in (await session.execute(tq.order_by(TopUp.id.desc()).limit(page * size))).scalars()]
    items.sort(key=lambda x: x["ts"], reverse=True)
    return {"items": items[(page - 1) * size: page * size], "page": page, "has_more": len(items) > page * size}


@router.get("/me/transactions/{tx_id}")
async def tx_detail(tx_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if tx_id.startswith("TOP-"):
        t = (await session.execute(select(TopUp).where(TopUp.public_id == tx_id, TopUp.user_id == user.id))).scalar_one_or_none()
        if not t:
            raise not_found()
        d = _topup_item(t) | {"rate_snapshot": t.rate_snapshot, "stars_amount": t.stars_amount, "review_note": t.review_note, "ledger_tx_id": t.ledger_tx_id}
    else:
        e = (await session.execute(select(LedgerEntry).where(LedgerEntry.tx_id == tx_id, LedgerEntry.user_id == user.id))).scalar_one_or_none()
        if not e:
            raise not_found()
        d = _ledger_item(e) | {"note": e.note}
    d["receipt"] = {"number": d["tx_id"], "issued_to": user.abu_id, "issued_at": now_utc().isoformat(), "valid": d["status"] == "success"}
    return d


# ------------------------------------------------------------------ to'ldirish
@router.get("/topup/options")
async def topup_options(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await topup_svc.options(session)


class TopUpIn(BaseModel):
    currency: str
    provider: str
    idempotency_key: str = Field(min_length=8, max_length=100)
    units: int | None = None
    package_id: int | None = None


@router.post("/topup")
async def create_topup(body: TopUpIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from ..providers.impls import PROVIDERS
    t, created = await topup_svc.create_topup(session, user, currency=body.currency, provider=body.provider, idem=body.idempotency_key,
                                              units=body.units, package_id=body.package_id)
    pay = await PROVIDERS[t.provider].create_payment(t, user)
    if t.provider == "stars":
        from ..bot.instance import create_stars_invoice
        link = await create_stars_invoice(t)
        if not link:
            raise DomainError("provider_not_configured", "Telegram Stars hozircha ishlamayapti (bot sozlanmagan)", 409)
        pay = {"type": "invoice", "url": link, "stars": t.stars_amount}
    return {"topup": topup_dict(t), "pay": pay}


@router.post("/topup/{public_id}/receipt")
async def upload_receipt(public_id: str, file: UploadFile = File(...), user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = (await session.execute(select(TopUp).where(TopUp.public_id == public_id, TopUp.user_id == user.id).with_for_update())).scalar_one_or_none()
    if not t:
        raise not_found()
    data = await file.read(settings.max_upload_bytes + 1)
    kind, mime = sniff_image(data, settings.max_upload_bytes, allow=("image",))
    await topup_svc.attach_receipt(session, t, data, mime)
    return topup_dict(t)


@router.get("/topups")
async def my_topups(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(TopUp).where(TopUp.user_id == user.id).order_by(TopUp.id.desc()).limit(50))).scalars()
    return [topup_dict(t) for t in rows]


# ------------------------------------------------------------------ bonuslar
@router.get("/bonus/daily")
async def daily_state(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await bonus.daily_state(session, user.id)


@router.post("/bonus/daily/claim")
async def daily_claim(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await bonus.claim_daily(session, user.id)


@router.get("/referral")
async def referral(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Referral, User).join(User, User.id == Referral.invited_id).where(Referral.referrer_id == user.id)
                                  .order_by(Referral.id.desc()).limit(100))).all()
    cnt = lambda s: sum(1 for r, _ in rows if r.status == s)
    return {"link": f"https://t.me/{settings.bot_username}?start=ref_{user.referral_code}", "code": user.referral_code,
            "reward_f": await settings_svc.get(session, "referral_reward_f"), "reward_ton": await settings_svc.get(session, "referral_reward_ton"),
            "wait_minutes": await settings_svc.get(session, "referral_wait_minutes"),
            "counts": {"total": len(rows), "pending": cnt("pending"), "rewarded": cnt("rewarded"), "rejected": cnt("rejected") + cnt("flagged")},
            "items": [{"name": u.first_name or u.abu_id, "abu_id": u.abu_id, "status": r.status, "qualifies_at": r.qualifies_at.isoformat(),
                       "created_at": r.created_at.isoformat()} for r, u in rows]}


class PromoIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)


@router.post("/promo/redeem")
async def redeem(body: PromoIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await bonus.redeem_promo(session, user, body.code)


@router.get("/vip")
async def vip(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await vip_for(session, user)


@router.get("/achievements")
async def achievements(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await check_achievements(session, user)
    got = set((await session.execute(select(UserAchievement.achievement_id).where(UserAchievement.user_id == user.id))).scalars())
    return [{"code": a.code, "title": a.title, "description": a.description, "icon": a.icon, "xp_reward": a.xp_reward, "unlocked": a.id in got}
            for a in (await session.execute(select(Achievement).where(Achievement.active.is_(True)).order_by(Achievement.id))).scalars()]


@router.get("/tasks")
async def tasks(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    done = set((await session.execute(select(UserTask.task_id).where(UserTask.user_id == user.id))).scalars())
    out = []
    for t in (await session.execute(select(Task).where(Task.active.is_(True)).order_by(Task.id))).scalars():
        out.append({"id": t.id, "title": t.title, "kind": t.kind, "currency": t.currency, "amount": t.amount, "xp": t.xp,
                    "claimed": t.id in done, "ready": t.id not in done and await social.task_done(session, user, t)})
    return out


@router.post("/tasks/{task_id}/claim")
async def claim_task(task_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await social.claim_task(session, user, task_id)


@router.get("/leaderboard")
async def leaderboard(period: str = "weekly", user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await social.leaderboard(session, period)


@router.get("/news")
async def news(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)):
    rows = (await session.execute(select(News).where(News.published.is_(True)).order_by(News.id.desc()).limit(30))).scalars()
    return [{"id": n.id, "title": n.title, "body": n.body, "created_at": n.created_at.isoformat()} for n in rows]


@router.get("/subscription")
async def subscription(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    r = await channels.check_subscription(session, user.telegram_id)
    return {"ok": r["ok"], "unverifiable": r["unverifiable"], "missing": [channels.channel_dict(c) for c in r["missing"]]}


# ------------------------------------------------------------------ bildirishnoma
@router.get("/notifications")
async def notifications(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(50))).scalars().all()
    unread = await session.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {"unread": unread, "items": [{"id": n.id, "type": n.type, "title": n.title, "body": n.body, "read": n.read_at is not None, "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read")
async def notifications_read(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from sqlalchemy import update
    await session.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=now_utc()))
    return {"ok": True}


# ------------------------------------------------------------------ support
class TicketIn(BaseModel):
    subject: str
    body: str


class MsgIn(BaseModel):
    body: str


@router.get("/support/faq")
async def faq(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return {"faq": await settings_svc.get(session, "faq"), "contact": settings.support_username or None}


@router.get("/support/tickets")
async def my_tickets(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(SupportTicket).where(SupportTicket.user_id == user.id).order_by(SupportTicket.updated_at.desc()).limit(50))).scalars()
    return [{"id": t.id, "subject": t.subject, "status": t.status, "updated_at": t.updated_at.isoformat()} for t in rows]


@router.post("/support/tickets")
async def new_ticket(body: TicketIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await social.create_ticket(session, user, body.subject, body.body)
    return {"id": t.id, "status": t.status}


@router.get("/support/tickets/{tid}")
async def ticket(tid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await session.get(SupportTicket, tid)
    if not t or t.user_id != user.id:
        raise not_found()
    msgs = (await session.execute(select(SupportMessage).where(SupportMessage.ticket_id == tid).order_by(SupportMessage.id))).scalars()
    return {"id": t.id, "subject": t.subject, "status": t.status, "messages": [{"staff": m.is_staff, "body": m.body, "created_at": m.created_at.isoformat()} for m in msgs]}


@router.post("/support/tickets/{tid}/messages")
async def ticket_msg(tid: int, body: MsgIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    t = await session.get(SupportTicket, tid)
    if not t or t.user_id != user.id:
        raise not_found()
    await social.ticket_reply(session, t, user, body.body, staff=False)
    return {"ok": True}
