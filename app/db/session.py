from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# Create async engine
engine: AsyncEngine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=settings.DEBUG,  # Log SQL queries in development
    future=True,
    pool_pre_ping=True,  # Verify connections before using them
    pool_size=20,  # Number of connections to keep in pool
    max_overflow=10,  # Additional connections beyond pool_size
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autoflush=False,
    autocommit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Create a new async database session.

    This is a simple factory function. For request-scoped sessions,
    use the dependency in app/api/deps.py instead.
    """
    async with async_session_maker() as session:
        yield session
