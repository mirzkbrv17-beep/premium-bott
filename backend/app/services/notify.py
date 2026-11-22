"""Bildirishnomalar DB'ga yoziladi (restartda yo'qolmaydi); botga yetkazishni scheduler bajaradi."""
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Notification, User


async def notify(session: AsyncSession, user_id: int, type_: str, title: str, body: str = "",
                 dedupe_key: str | None = None) -> None:
    dialect = session.bind.dialect.name if session.bind else "postgresql"
    ins = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = ins(Notification).values(user_id=user_id, type=type_, title=title[:160], body=body[:1000],
                                    dedupe_key=dedupe_key, send_attempts=0)
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
    await session.execute(stmt)
