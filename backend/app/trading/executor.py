"""Exécution MOCKÉE (paper trading) — SEULE partie simulée du système.

Aucun appel à l'API privée Kraken : les ordres virtuels sont enregistrés
en base avec un statut de succès simulé.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import PaperOrder
from ..llm.agent import LLMVerdict
from ..quant.engine import DeterministicResult

logger = logging.getLogger(__name__)


class MockPaperExecutor:
    def __init__(self, notional_usd: float = 100.0) -> None:
        self._notional = notional_usd

    # -- création ----------------------------------------------------------
    async def propose(
        self,
        session: AsyncSession,
        det: DeterministicResult,
        verdict: LLMVerdict,
        mode: str,
        auto_fill: bool,
    ) -> PaperOrder | None:
        """Crée un ordre virtuel si le verdict LLM est directionnel.

        - FULL_AUTO (auto_fill=True) : statut FILLED immédiat (succès simulé).
        - HITM (auto_fill=False) : statut PENDING, en attente de validation.
        - HOLD ou prix invalide : aucun ordre (None).
        """
        if verdict.signal == "HOLD":
            return None
        if det.last_price <= 0:
            logger.warning("%s: prix invalide, ordre ignoré.", det.pair)
            return None

        quantity = self._notional / det.last_price
        now = datetime.now(timezone.utc)
        order = PaperOrder(
            pair=det.pair,
            side=verdict.signal,  # LONG | SHORT
            det_signal=det.signal,
            det_score=det.confidence,
            llm_signal=verdict.signal,
            llm_score=verdict.confidence,
            llm_justification=verdict.justification,
            price=det.last_price,
            quantity=quantity,
            notional_usd=self._notional,
            status="FILLED" if auto_fill else "PENDING",
            mode_at_creation=mode,
            filled_at=now if auto_fill else None,
            decided_by="system" if auto_fill else "pending-human",
            llm_raw=verdict.raw,
        )
        session.add(order)
        await session.flush()
        logger.info(
            "Ordre virtuel %s %s %s @ %.4f [%s]",
            order.id[:8],
            det.pair,
            verdict.signal,
            det.last_price,
            order.status,
        )
        return order

    # -- validation humaine (HITM) ------------------------------------------
    async def approve(self, session: AsyncSession, order_id: str) -> PaperOrder | None:
        order = await self._get_pending(session, order_id)
        if order is None:
            return None
        order.status = "FILLED"  # succès simulé
        order.filled_at = datetime.now(timezone.utc)
        order.decided_by = "human"
        await session.flush()
        logger.info("Ordre %s APPROUVÉ par humain (paper FILLED).", order_id[:8])
        return order

    async def reject(self, session: AsyncSession, order_id: str) -> PaperOrder | None:
        order = await self._get_pending(session, order_id)
        if order is None:
            return None
        order.status = "REJECTED"
        order.decided_by = "human"
        await session.flush()
        logger.info("Ordre %s REJETÉ par humain.", order_id[:8])
        return order

    @staticmethod
    async def _get_pending(session: AsyncSession, order_id: str) -> PaperOrder | None:
        res = await session.execute(
            select(PaperOrder).where(
                PaperOrder.id == order_id, PaperOrder.status == "PENDING"
            )
        )
        return res.scalars().first()
