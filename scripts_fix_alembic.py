"""Bazadagi noma'lum alembic revision'ni tozalaydi (eski deploy qoldig'i). Faqat bo'sh/yangi bazada xavfsiz."""
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

KNOWN = {"0001"}

async def main():
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)
    eng = create_async_engine(url)
    async with eng.begin() as c:
        has = await c.scalar(text("select to_regclass('public.alembic_version')"))
        if has:
            revs = [r for (r,) in (await c.execute(text("select version_num from alembic_version"))).all()]
            bad = [r for r in revs if r not in KNOWN]
            if bad:
                print("noma'lum revision topildi, tozalanmoqda:", bad)
                await c.execute(text("delete from alembic_version"))
    await eng.dispose()

asyncio.run(main())
