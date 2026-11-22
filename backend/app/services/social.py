"""ABU GIFT, do'stlar, duel, kun savoli, tasks, leaderboard, support."""
import random
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError, forbidden, not_found
from ..models import (CURRENCIES, DailyQuestionAnswer, Dispute, Duel, Friend, GiftTransfer, Order, Question, Referral,
                      SupportMessage, SupportTicket, Task, TopUp, User, UserTask, XpEvent, utcnow)
from ..timeutil import now_utc, tashkent_date
from . import audit, channels, ledger, settings_svc
from .market import system_user
from .notify import notify
from .progress import add_xp, check_achievements


# ------------------------------------------------------------------ ABU GIFT
async def send_gift(session: AsyncSession, sender: User, *, to_abu_id: str, currency: str, amount: int, message: str | None, idem: str) -> tuple[GiftTransfer, bool]:
    ex = (await session.execute(select(GiftTransfer).where(GiftTransfer.sender_id == sender.id, GiftTransfer.idempotency_key == idem))).scalar_one_or_none()
    if ex:
        return ex, False
    if currency not in CURRENCIES or amount < 1:
        raise DomainError("bad_amount", "Miqdor yoki valyuta noto'g'ri")
    rcv = (await session.execute(select(User).where(User.abu_id == to_abu_id.strip().upper(), User.kind == "user"))).scalar_one_or_none()
    if not rcv or rcv.is_banned:
        raise not_found("Qabul qiluvchi topilmadi")
    if rcv.id == sender.id:
        raise DomainError("self_gift", "O'zingizga sovg'a qila olmaysiz")
    age_h = int(await settings_svc.get(session, "gift_min_account_age_hours"))
    if now_utc() - sender.created_at < timedelta(hours=age_h):
        raise DomainError("account_too_new", f"Sovg'a yuborish uchun akkaunt {age_h} soatdan eski bo'lishi kerak", 403)
    lock = await session.get(User, sender.id, with_for_update=True)  # kunlik limitni parallel aylanib o'tishdan himoya
    day_start = now_utc() - timedelta(days=1)
    sent = await session.scalar(select(func.coalesce(func.sum(GiftTransfer.amount), 0)).where(
        GiftTransfer.sender_id == sender.id, GiftTransfer.currency == currency, GiftTransfer.status != "rejected", GiftTransfer.created_at >= day_start))
    limit = int((await settings_svc.get(session, "gift_daily_limit"))[currency])
    if sent + amount > limit:
        raise DomainError("daily_limit", f"Kunlik sovg'a limiti: {limit}", 429)
    threshold = int((await settings_svc.get(session, "gift_review_threshold"))[currency])
    review = amount >= threshold
    g = GiftTransfer(sender_id=sender.id, receiver_id=rcv.id, currency=currency, amount=amount, message=(message or "")[:200],
                     status="pending_review" if review else "completed", idempotency_key=idem)
    session.add(g)
    await session.flush()
    await ledger.post_entry(session, user_id=sender.id, currency=currency, amount=-amount, kind="gift_out", idem=f"gift:{g.public_id}:out", ref_type="gift", ref_id=g.public_id)
    if review:  # katta summa: admin tasdig'igacha escrow'da
        esc = await system_user(session, "escrow")
        await ledger.post_entry(session, user_id=esc.id, currency=currency, amount=amount, kind="gift_hold", idem=f"gift:{g.public_id}:hold", ref_type="gift", ref_id=g.public_id)
    else:
        await _deliver_gift(session, g)
    await check_achievements(session, sender)
    return g, True


async def _deliver_gift(session, g: GiftTransfer) -> None:
    await ledger.post_entry(session, user_id=g.receiver_id, currency=g.currency, amount=g.amount, kind="gift_in", idem=f"gift:{g.public_id}:in", ref_type="gift", ref_id=g.public_id)
    sender = await session.get(User, g.sender_id)
    await notify(session, g.receiver_id, "bonus", "🎁 Sovg'a oldingiz", f"{sender.first_name}: +{g.amount} {g.currency.replace('_', ' ')}", dedupe_key=f"gift:{g.id}")


async def review_gift(session, gift_id: int, approve: bool, admin_id: int, ip=None) -> GiftTransfer:
    g = (await session.execute(select(GiftTransfer).where(GiftTransfer.id == gift_id).with_for_update())).scalar_one_or_none()
    if not g:
        raise not_found()
    if g.status != "pending_review":
        raise DomainError("already_processed", "Sovg'a allaqachon ko'rib chiqilgan", 409)
    esc = await system_user(session, "escrow")
    await ledger.post_entry(session, user_id=esc.id, currency=g.currency, amount=-g.amount, kind="gift_hold", idem=f"gift:{g.public_id}:release", ref_type="gift", ref_id=g.public_id)
    if approve:
        g.status = "completed"
        await _deliver_gift(session, g)
    else:
        g.status = "rejected"
        await ledger.post_entry(session, user_id=g.sender_id, currency=g.currency, amount=g.amount, kind="gift_refund", idem=f"gift:{g.public_id}:refund", ref_type="gift", ref_id=g.public_id)
    await audit.log(session, admin_id, "gift.approve" if approve else "gift.reject", "gift", g.public_id, {"amount": g.amount, "currency": g.currency}, ip)
    return g


# ------------------------------------------------------------------ do'stlar / duel / savol
async def friend_request(session, user: User, abu_id: str) -> Friend:
    other = (await session.execute(select(User).where(User.abu_id == abu_id.strip().upper(), User.kind == "user"))).scalar_one_or_none()
    if not other or other.id == user.id:
        raise not_found("Foydalanuvchi topilmadi")
    ex = (await session.execute(select(Friend).where(or_((Friend.user_id == user.id) & (Friend.friend_id == other.id), (Friend.user_id == other.id) & (Friend.friend_id == user.id))))).scalar_one_or_none()
    if ex:
        if ex.status == "pending" and ex.friend_id == user.id:
            ex.status = "accepted"
            return ex
        raise DomainError("exists", "So'rov yoki do'stlik allaqachon mavjud", 409)
    f = Friend(user_id=user.id, friend_id=other.id)
    session.add(f)
    await session.flush()
    await notify(session, other.id, "bonus", "👥 Do'stlik so'rovi", f"{user.first_name} ({user.abu_id})")
    return f


async def friend_accept(session, user: User, fid: int) -> Friend:
    f = await session.get(Friend, fid)
    if not f or f.friend_id != user.id:
        raise not_found()
    f.status = "accepted"
    return f


async def are_friends(session, a: int, b: int) -> bool:
    return bool(await session.scalar(select(Friend.id).where(Friend.status == "accepted", or_((Friend.user_id == a) & (Friend.friend_id == b), (Friend.user_id == b) & (Friend.friend_id == a)))))


async def today_question(session, user: User) -> dict:
    qs = (await session.execute(select(Question).where(Question.active.is_(True)).order_by(Question.id))).scalars().all()
    if not qs:
        return {"available": False}
    today = tashkent_date()
    q = qs[today.toordinal() % len(qs)]
    ans = await session.scalar(select(DailyQuestionAnswer).where(DailyQuestionAnswer.user_id == user.id, DailyQuestionAnswer.answer_date == today))
    return {"available": True, "id": q.id, "text": q.text, "options": q.options, "answered": ans is not None, "correct": ans.correct if ans else None}


async def answer_question(session, user: User, index: int) -> dict:
    info = await today_question(session, user)
    if not info["available"]:
        raise not_found("Bugun savol yo'q")
    if info["answered"]:
        raise DomainError("already_answered", "Bugun javob bergansiz", 409)
    q = await session.get(Question, info["id"])
    ok = index == q.correct_index
    session.add(DailyQuestionAnswer(user_id=user.id, answer_date=tashkent_date(), question_id=q.id, correct=ok))
    await session.flush()
    xp = int(await settings_svc.get(session, "daily_question_xp")) if ok else 1
    await add_xp(session, user.id, xp, "question")
    return {"correct": ok, "correct_index": q.correct_index, "xp": xp}


async def create_duel(session, user: User, friend_abu_id: str) -> Duel:
    other = (await session.execute(select(User).where(User.abu_id == friend_abu_id.strip().upper()))).scalar_one_or_none()
    if not other or not await are_friends(session, user.id, other.id):
        raise DomainError("not_friend", "Duel faqat do'stlar o'rtasida", 403)
    ids = list((await session.execute(select(Question.id).where(Question.active.is_(True)))).scalars())
    if len(ids) < 3:
        raise DomainError("no_questions", "Savollar yetarli emas", 409)
    d = Duel(challenger_id=user.id, opponent_id=other.id, question_ids=random.sample(ids, 3))
    session.add(d)
    await session.flush()
    await notify(session, other.id, "bonus", "⚔️ Duelga chaqiruv", f"{user.first_name} sizni viktorina duelga chaqirdi (pul tikishsiz)")
    return d


async def duel_accept(session, user: User, did: int, accept: bool) -> Duel:
    d = await session.get(Duel, did, with_for_update=True)
    if not d or d.opponent_id != user.id or d.status != "invited":
        raise not_found()
    d.status = "active" if accept else "declined"
    return d


async def duel_answer(session, user: User, did: int, answers: list[int]) -> dict:
    d = await session.get(Duel, did, with_for_update=True)
    if not d or user.id not in (d.challenger_id, d.opponent_id) or d.status != "active":
        raise not_found()
    me_c = user.id == d.challenger_id
    if (d.challenger_score if me_c else d.opponent_score) is not None:
        raise DomainError("already_answered", "Javob yuborilgan", 409)
    if len(answers) != len(d.question_ids):
        raise DomainError("bad_request", "Javoblar soni noto'g'ri")
    score = 0
    for qid, a in zip(d.question_ids, answers):
        q = await session.get(Question, qid)
        score += int(q.correct_index == a)
    if me_c:
        d.challenger_score = score
    else:
        d.opponent_score = score
    if d.challenger_score is not None and d.opponent_score is not None:
        d.status = "finished"
        d.winner_id = None if d.challenger_score == d.opponent_score else (d.challenger_id if d.challenger_score > d.opponent_score else d.opponent_id)
        for uid in (d.challenger_id, d.opponent_id):
            await add_xp(session, uid, 15 if uid == d.winner_id else 5, "duel")
    return {"score": score, "status": d.status, "winner_id": d.winner_id}


# ------------------------------------------------------------------ tasks
async def task_done(session, user: User, t: Task) -> bool:
    c = lambda q: session.scalar(q)
    if t.kind == "first_order":
        return bool(await c(select(func.count(Order.id)).where(Order.user_id == user.id, Order.status.notin_(["refunded", "cancelled"]))))
    if t.kind == "first_topup":
        return bool(await c(select(func.count(TopUp.id)).where(TopUp.user_id == user.id, TopUp.status == "success")))
    if t.kind == "invite_1":
        return bool(await c(select(func.count(Referral.id)).where(Referral.referrer_id == user.id, Referral.status == "rewarded")))
    if t.kind == "level_5":
        return user.xp >= 400
    if t.kind == "join_channel" and t.param:
        chk = channels._checker
        return bool(chk and user.telegram_id and await chk(t.param, user.telegram_id))
    return False


async def claim_task(session, user: User, task_id: int) -> dict:
    t = await session.get(Task, task_id)
    if not t or not t.active:
        raise not_found()
    await session.get(User, user.id, with_for_update=True)
    if await session.scalar(select(UserTask.id).where(UserTask.user_id == user.id, UserTask.task_id == t.id)):
        raise DomainError("already_claimed", "Vazifa mukofoti olingan", 409)
    if not await task_done(session, user, t):
        raise DomainError("not_done", "Vazifa shartlari hali bajarilmagan (server tekshirdi)", 409)
    session.add(UserTask(user_id=user.id, task_id=t.id))
    await session.flush()
    await ledger.post_entry(session, user_id=user.id, currency=t.currency, amount=t.amount, kind="bonus_task", idem=f"task:{t.id}:{user.id}", ref_type="task", ref_id=t.code)
    await add_xp(session, user.id, t.xp, "task")
    return {"amount": t.amount, "currency": t.currency}


# ------------------------------------------------------------------ leaderboard
async def leaderboard(session, period: str, limit: int = 20) -> list[dict]:
    q = select(XpEvent.user_id, func.sum(XpEvent.amount).label("xp")).group_by(XpEvent.user_id)
    now = now_utc()
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period)
    if period != "all" and days is None:
        raise DomainError("bad_period", "Davr noto'g'ri")
    if days:
        q = q.where(XpEvent.created_at >= now - timedelta(days=days))
    rows = (await session.execute(q.order_by(func.sum(XpEvent.amount).desc()).limit(limit))).all()
    out = []
    for i, (uid, xp) in enumerate(rows, 1):
        u = await session.get(User, uid)
        if u.kind == "user" and not u.is_banned:
            out.append({"rank": i, "abu_id": u.abu_id, "name": u.first_name or u.abu_id, "photo_url": u.photo_url, "xp": int(xp)})
    return out


# ------------------------------------------------------------------ support
async def create_ticket(session, user: User, subject: str, body: str) -> SupportTicket:
    subject, body = (subject or "").strip(), (body or "").strip()
    if not (3 <= len(subject) <= 160) or not (1 <= len(body) <= 2000):
        raise DomainError("bad_request", "Mavzu yoki matn noto'g'ri")
    t = SupportTicket(user_id=user.id, subject=subject)
    session.add(t)
    await session.flush()
    session.add(SupportMessage(ticket_id=t.id, author_id=user.id, body=body))
    return t


async def ticket_reply(session, ticket: SupportTicket, author: User, body: str, staff: bool) -> SupportMessage:
    body = (body or "").strip()
    if not body or len(body) > 2000:
        raise DomainError("bad_request", "Xabar noto'g'ri")
    if ticket.status == "closed" and not staff:
        raise DomainError("closed", "Murojaat yopilgan", 409)
    m = SupportMessage(ticket_id=ticket.id, author_id=author.id, is_staff=staff, body=body)
    session.add(m)
    ticket.status = "answered" if staff else "open"
    ticket.updated_at = utcnow()
    if staff:
        await notify(session, ticket.user_id, "support", "💬 Support javob berdi", ticket.subject)
    await session.flush()
    return m
