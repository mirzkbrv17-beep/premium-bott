from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

engine = create_async_engine(settings.db_url, pool_pre_ping=True, pool_size=10, max_overflow=10) \
    if not settings.db_url.startswith("sqlite") else create_async_engine(settings.db_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session():
    """Har so'rov = bitta tranzaksiya. Xato bo'lsa rollback, aks holda commit."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
