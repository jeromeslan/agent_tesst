"""Modèles ORM — TimescaleDB (Hypertables) avec fallback SQLite pour le dev."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisCycle(Base):
    """Un cycle d'analyse complet (quant + LLM) pour une paire.

    Hypertable TimescaleDB partitionnée sur `time`.
    """

    __tablename__ = "analysis_cycles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    pair: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # "MULTI" = agrégation M1/M5/M15 ; détail par timeframe dans `indicators`.
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, default="MULTI")

    det_signal: Mapped[str] = mapped_column(String(10), nullable=False)
    det_score: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_signal: Mapped[str] = mapped_column(String(10), nullable=False)
    llm_score: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_justification: Mapped[str] = mapped_column(Text, nullable=False, default="")

    last_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="HITM")

    # Indicateurs par timeframe + analyse volume (JSON).
    indicators: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # Payload brut renvoyé par le LLM (JSONB).
    llm_raw: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))


class PaperOrder(Base):
    """Ordre virtuel (paper trading mocké) — jamais envoyé à Kraken."""

    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    pair: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # LONG | SHORT

    det_signal: Mapped[str] = mapped_column(String(10), nullable=False)
    det_score: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_signal: Mapped[str] = mapped_column(String(10), nullable=False)
    llm_score: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_justification: Mapped[str] = mapped_column(Text, nullable=False, default="")

    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    notional_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # PENDING (attente validation HITM) | FILLED | REJECTED
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING", index=True)
    mode_at_creation: Mapped[str] = mapped_column(String(10), nullable=False)

    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    llm_raw: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
