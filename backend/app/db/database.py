"""Moteur SQLAlchemy asynchrone + initialisation TimescaleDB."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import get_settings
from .models import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"echo": False, "pool_pre_ping": True}
        if settings.is_sqlite:
            # SQLite (aiosqlite/NullPool) : pas de pool_size/max_overflow.
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update({"pool_size": 5, "max_overflow": 10})
        _engine = create_async_engine(settings.database_url, **kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : session async par requête."""
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    """Crée les tables + convertit en Hypertables TimescaleDB (idempotent)."""
    settings = get_settings()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if not settings.is_sqlite:
            for table in ("analysis_cycles", "paper_orders"):
                try:
                    await conn.execute(
                        text(
                            "SELECT create_hypertable(:table, 'time', "
                            "if_not_exists => TRUE, migrate_data => TRUE)"
                        ),
                        {"table": table},
                    )
                    logger.info("Hypertable TimescaleDB OK : %s", table)
                except Exception as exc:  # extension absente ? on log, on continue
                    logger.warning(
                        "create_hypertable(%s) impossible (%s) — "
                        "la table reste une table PostgreSQL classique.",
                        table,
                        exc,
                    )


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
