"""Ledger - pul/valyuta harakatining yagona kirish nuqtasi.

Qoidalar: yozuvlar o'zgarmas; har biri unikal idempotency_key bilan; hisob qatori FOR UPDATE
bilan qulflanadi (parallel so'rovlar ketma-ket bajariladi); balans hech qachon manfiy bo'lmaydi.
"""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError, InsufficientFunds
from ..models import CURRENCIES, BalanceAccount, LedgerEntry

SPEND_KINDS = {"purchase", "rental"}


async def ensure_accounts(session: AsyncSession, user_id: int) -> None:
    dialect = session.bind.dialect.name if session.bind else "postgresql"
    ins = pg_insert if dialect == "postgresql" else sqlite_insert
    for cur in CURRENCIES:
        await session.execute(ins(BalanceAccount).values(user_id=user_id, currency=cur, balance=0,
                                                         topped_up_total=0, spent_total=0)
                              .on_conflict_do_nothing(index_elements=["user_id", "currency"]))
    await session.flush()


async def _locked_account(session: AsyncSession, user_id: int, currency: str) -> BalanceAccount:
    if currency not in CURRENCIES:
        raise DomainError("bad_currency", "Noma'lum valyuta")
    q = select(BalanceAccount).where(BalanceAccount.user_id == user_id, BalanceAccount.currency == currency) \
        .with_for_update()
    acc = (await session.execute(q)).scalar_one_or_none()
    if acc is None:
        await ensure_accounts(session, user_id)
        acc = (await session.execute(q)).scalar_one()
    return acc


async def post_entry(session: AsyncSession, *, user_id: int, currency: str, amount: int, kind: str, idem: str,
                     ref_type: str | None = None, ref_id: str | None = None, note: str | None = None,
                     meta: dict | None = None, admin_id: int | None = None,
                     reverses_id: int | None = None) -> tuple[LedgerEntry, bool]:
    """Yozuv qo'shadi. Qaytaradi: (entry, created). Takror idem -> mavjud yozuv, created=False."""
    if not isinstance(amount, int) or amount == 0:
        raise DomainError("bad_amount", "Miqdor noto'g'ri")
    acc = await _locked_account(session, user_id, currency)
    existing = (await session.execute(select(LedgerEntry).where(LedgerEntry.idempotency_key == idem))).scalar_one_or_none()
    if existing:  # qulfdan keyin tekshiramiz - parallel takrorlar shu yerda to'xtaydi
        if (existing.user_id, existing.currency, existing.amount) != (user_id, currency, amount):
            raise DomainError("idempotency_conflict", "Idempotency kaliti boshqa amal uchun ishlatilgan", 409)
        return existing, False
    new_balance = acc.balance + amount
    if new_balance < 0:
        raise InsufficientFunds(currency)
    acc.balance = new_balance
    if kind == "topup":
        acc.topped_up_total += amount
    elif kind in SPEND_KINDS and amount < 0:
        acc.spent_total += -amount
    elif kind == "refund" and amount > 0:
        acc.spent_total = max(0, acc.spent_total - amount)
    entry = LedgerEntry(user_id=user_id, account_id=acc.id, currency=currency, amount=amount,
                        balance_after=new_balance, kind=kind, ref_type=ref_type, ref_id=ref_id,
                        idempotency_key=idem, note=note, meta=meta or {}, admin_user_id=admin_id,
                        reverses_id=reverses_id)
    session.add(entry)
    await session.flush()
    return entry, True


async def reverse_entry(session: AsyncSession, entry: LedgerEntry, *, idem: str, kind: str = "reversal",
                        note: str | None = None, admin_id: int | None = None) -> tuple[LedgerEntry, bool]:
    """Tuzatish - eski yozuvga teginmay, teskari yozuv qo'shadi."""
    return await post_entry(session, user_id=entry.user_id, currency=entry.currency, amount=-entry.amount,
                            kind=kind, idem=idem, ref_type=entry.ref_type, ref_id=entry.ref_id, note=note,
                            admin_id=admin_id, reverses_id=entry.id)


async def balances(session: AsyncSession, user_id: int) -> dict:
    rows = (await session.execute(select(BalanceAccount).where(BalanceAccount.user_id == user_id))).scalars().all()
    out = {c: {"balance": 0, "topped_up": 0, "spent": 0} for c in CURRENCIES}
    for r in rows:
        out[r.currency] = {"balance": r.balance, "topped_up": r.topped_up_total, "spent": r.spent_total}
    return out
