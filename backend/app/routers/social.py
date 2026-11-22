from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import Duel, Friend, GiftTransfer, User
from ..services import social as svc

router = APIRouter(prefix="/api")


class GiftIn(BaseModel):
    to_abu_id: str
    currency: str
    amount: int = Field(ge=1)
    message: str | None = Field(None, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=100)


@router.post("/gifts")
async def gift(body: GiftIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    g, _ = await svc.send_gift(session, user, to_abu_id=body.to_abu_id, currency=body.currency, amount=body.amount, message=body.message, idem=body.idempotency_key)
    return {"id": g.public_id, "status": g.status}


@router.get("/gifts")
async def my_gifts(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(GiftTransfer).where(or_(GiftTransfer.sender_id == user.id, GiftTransfer.receiver_id == user.id)).order_by(GiftTransfer.id.desc()).limit(100))).scalars()
    out = []
    for g in rows:
        other = await session.get(User, g.receiver_id if g.sender_id == user.id else g.sender_id)
        out.append({"id": g.public_id, "direction": "out" if g.sender_id == user.id else "in", "other": other.first_name or other.abu_id, "other_abu_id": other.abu_id,
                    "currency": g.currency, "amount": g.amount, "message": g.message, "status": g.status, "created_at": g.created_at.isoformat()})
    return out


class AbuIdIn(BaseModel):
    abu_id: str


@router.get("/friends")
async def friends(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Friend).where(or_(Friend.user_id == user.id, Friend.friend_id == user.id)))).scalars()
    out = []
    for f in rows:
        oid = f.friend_id if f.user_id == user.id else f.user_id
        o = await session.get(User, oid)
        out.append({"id": f.id, "status": f.status, "incoming": f.friend_id == user.id and f.status == "pending", "name": o.first_name or o.abu_id, "abu_id": o.abu_id})
    return out


@router.post("/friends/request")
async def friend_req(body: AbuIdIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    f = await svc.friend_request(session, user, body.abu_id)
    return {"id": f.id, "status": f.status}


@router.post("/friends/{fid}/accept")
async def friend_acc(fid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    f = await svc.friend_accept(session, user, fid)
    return {"id": f.id, "status": f.status}


@router.get("/question/today")
async def question(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await svc.today_question(session, user)


class AnswerIn(BaseModel):
    index: int = Field(ge=0, le=10)


@router.post("/question/answer")
async def answer(body: AnswerIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await svc.answer_question(session, user, body.index)


@router.get("/duels")
async def duels(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from ..models import Question
    rows = (await session.execute(select(Duel).where(or_(Duel.challenger_id == user.id, Duel.opponent_id == user.id)).order_by(Duel.id.desc()).limit(30))).scalars()
    out = []
    for d in rows:
        o = await session.get(User, d.opponent_id if d.challenger_id == user.id else d.challenger_id)
        qs = []
        if d.status == "active":
            for qid in d.question_ids:
                q = await session.get(Question, qid)
                qs.append({"text": q.text, "options": q.options})  # to'g'ri javob yuborilmaydi
        mine_done = (d.challenger_score if d.challenger_id == user.id else d.opponent_score) is not None
        out.append({"id": d.id, "status": d.status, "opponent": o.first_name or o.abu_id, "incoming": d.opponent_id == user.id and d.status == "invited",
                    "questions": qs if not mine_done else [], "answered": mine_done, "winner_me": d.winner_id == user.id if d.winner_id else None,
                    "my_score": d.challenger_score if d.challenger_id == user.id else d.opponent_score})
    return out


@router.post("/duels")
async def duel_new(body: AbuIdIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    d = await svc.create_duel(session, user, body.abu_id)
    return {"id": d.id}


class AcceptIn(BaseModel):
    accept: bool = True


@router.post("/duels/{did}/accept")
async def duel_acc(did: int, body: AcceptIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    d = await svc.duel_accept(session, user, did, body.accept)
    return {"status": d.status}


class DuelAnswers(BaseModel):
    answers: list[int]


@router.post("/duels/{did}/answer")
async def duel_ans(did: int, body: DuelAnswers, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await svc.duel_answer(session, user, did, body.answers)
