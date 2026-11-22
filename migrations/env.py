import asyncio

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models import Base

target_metadata = Base.metadata
LOCK_ID = 727274  # ko'p instansda bir vaqtda migratsiya qilinmasligi uchun


def _run(connection):
    if connection.dialect.name == "postgresql":
        connection.execute(text(f"select pg_advisory_lock({LOCK_ID})"))
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
    if connection.dialect.name == "postgresql":
        connection.execute(text(f"select pg_advisory_unlock({LOCK_ID})"))


async def run_async():
    engine = create_async_engine(settings.db_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=settings.db_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async())
