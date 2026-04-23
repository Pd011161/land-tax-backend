"""
─────────────────────
Async SQLAlchemy engine + session factory
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.parcel import Base

_engine = None
_session_factory = None


def init_db(database_url: str) -> None:
    """เรียกตอน startup — สร้าง engine จาก DATABASE_URL"""
    global _engine, _session_factory
    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def create_tables() -> None:
    """สร้าง tables ถ้ายังไม่มี (dev only — production ใช้ alembic)"""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """FastAPI dependency"""
    async with _session_factory() as session:
        yield session


async def close_db() -> None:
    if _engine:
        await _engine.dispose()