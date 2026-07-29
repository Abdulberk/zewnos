"""Veritabani baglantisi.

SQLite + aiosqlite: kurulum gerektirmez, reviewer `pip install` disinda hicbir
sey yapmaz. Uctan uca async oldugu icin FastAPI'nin event loop'u hicbir yerde
bloklanmaz.

Postgres'e gecis tek satir: DATABASE_URL'i `postgresql+asyncpg://...` yap.
SQLAlchemy'yi bu yuzden kullaniyoruz -- iki tablo icin ORM biraz agir gelebilir
ama tasima maliyetini sifira indiriyor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=False, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def create_all() -> None:
    if _engine is None:
        raise RuntimeError("init_engine() cagrilmadi.")
    from app.storage import models  # noqa: F401 -- tablolarin kayit olmasi icin

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends saglayicisi."""
    if _session_factory is None:
        raise RuntimeError("init_engine() cagrilmadi.")
    async with _session_factory() as session:
        yield session
