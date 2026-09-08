"""Pipeline orchestrateur : Kraken -> Quant -> LLM -> TimescaleDB -> Exécution.

Cycle de vie :
  1. bootstrap REST (historique M1/M5/M15 par paire),
  2. démarrage du WS live (clôtures temps réel),
  3. boucle d'analyse périodique (toutes les N secondes) :
     moteur déterministe -> agent LLM -> insert async en Hypertable ->
     décision d'exécution selon le mode (FULL_AUTO / HITM).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import desc, select

from ..config import get_settings
from ..db.database import get_session_factory
from ..db.models import AnalysisCycle, PaperOrder
from ..kraken.rest import fetch_ohlc_history
from ..kraken.store import Candle, CandleStore
from ..kraken.websocket import KrakenWSClient
from ..llm.agent import LLMAgent, LLMVerdict
from ..quant.engine import DeterministicEngine, DeterministicResult
from ..trading.executor import MockPaperExecutor
from ..trading.modes import ModeManager

logger = logging.getLogger(__name__)


class TradingPipeline:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.store = CandleStore(maxlen=settings.kraken_history_candles + 120)
        self.engine = DeterministicEngine(self.store)
        self.llm = LLMAgent()
        self.modes = ModeManager(
            initial=settings.execution_mode, threshold=settings.confidence_threshold
        )
        self.executor = MockPaperExecutor(notional_usd=settings.paper_notional_usd)
        self.ws = KrakenWSClient(
            ws_url=settings.kraken_ws_url,
            pairs=settings.trading_pairs,
            timeframes=settings.trading_timeframes,
            on_candle=self._on_live_candle,
        )
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._llm_semaphore = asyncio.Semaphore(2)  # limite les appels LLM concurrents
        self._latest: dict[str, dict] = {}
        self._latest_lock = asyncio.Lock()
        self._last_cycle_at: datetime | None = None
        self._cycles_count = 0

    # -- cycle de vie -------------------------------------------------------
    async def start(self) -> None:
        await self._bootstrap()
        await self.ws.start()
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="trading-pipeline")
        logger.info("Pipeline démarré (intervalle %ds).", self.settings.pipeline_interval_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.ws.stop()

    async def _bootstrap(self) -> None:
        """Charge l'historique REST pour chaque (paire, timeframe), en parallèle."""

        async def _one(pair: str, tf: int) -> None:
            try:
                candles = await fetch_ohlc_history(
                    self.settings.kraken_rest_url,
                    pair,
                    tf,
                    timeout=self.settings.kraken_rest_timeout,
                )
                await self.store.replace(
                    pair, tf, candles[-self.settings.kraken_history_candles :]
                )
            except Exception as exc:  # noqa: BLE001 - une paire ne bloque pas les autres
                logger.error("Bootstrap %s M%d impossible : %s", pair, tf, exc)

        await asyncio.gather(
            *(
                _one(pair, tf)
                for pair in self.settings.trading_pairs
                for tf in self.settings.trading_timeframes
            )
        )

    # -- callbacks WS --------------------------------------------------------
    async def _on_live_candle(self, pair: str, timeframe: int, candle: Candle, is_new: bool) -> None:
        await self.store.upsert_live(pair, timeframe, candle)

    # -- boucle d'analyse ----------------------------------------------------
    async def _loop(self) -> None:
        # Premier cycle immédiat, puis cadence régulière.
        while not self._stop.is_set():
            try:
                await self.run_cycle()
            except Exception:  # noqa: BLE001 - la boucle ne doit jamais mourir
                logger.exception("Erreur inattendue dans le cycle d'analyse.")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.pipeline_interval_seconds
                )
                break
            except TimeoutError:
                continue

    async def run_cycle(self) -> list[dict]:
        """Exécute un cycle complet pour toutes les paires. Retourne les états."""
        mode = await self.modes.get_mode()
        threshold = await self.modes.get_threshold()
        results = await asyncio.gather(
            *(self._analyze_pair(pair, mode, threshold) for pair in self.settings.trading_pairs)
        )
        states = [r for r in results if r is not None]
        async with self._latest_lock:
            for state in states:
                self._latest[state["pair"]] = state
        self._last_cycle_at = datetime.now(timezone.utc)
        self._cycles_count += 1
        return states

    async def _analyze_pair(self, pair: str, mode: str, threshold: int) -> dict | None:
        try:
            det: DeterministicResult = await self.engine.analyze(
                pair, self.settings.trading_timeframes
            )
            async with self._llm_semaphore:
                verdict: LLMVerdict = await self.llm.review(det)

            order_info: dict | None = None
            async with get_session_factory()() as session:
                # 1) Persistance du cycle (insert async -> Hypertable)
                session.add(
                    AnalysisCycle(
                        pair=pair,
                        timeframe="MULTI",
                        det_signal=det.signal,
                        det_score=det.confidence,
                        llm_signal=verdict.signal,
                        llm_score=verdict.confidence,
                        llm_justification=verdict.justification,
                        last_price=det.last_price,
                        volume=det.last_volume,
                        mode=mode,
                        indicators=det.to_dict(),
                        llm_raw={
                            "verdict": {
                                "signal": verdict.signal,
                                "confidence": verdict.confidence,
                                "justification": verdict.justification,
                            },
                            "model": verdict.model,
                            "provider": verdict.provider,
                            "latency_ms": verdict.latency_ms,
                            "fallback": verdict.fallback,
                            "raw": verdict.raw,
                        },
                    )
                )
                # 2) Décision d'exécution
                if verdict.signal != "HOLD" and verdict.confidence >= threshold:
                    if mode == "FULL_AUTO":
                        order = await self.executor.propose(
                            session, det, verdict, mode, auto_fill=True
                        )
                    else:  # HITM : mise en attente de validation humaine
                        order = await self.executor.propose(
                            session, det, verdict, mode, auto_fill=False
                        )
                    if order is not None:
                        order_info = {
                            "id": order.id,
                            "side": order.side,
                            "status": order.status,
                            "price": order.price,
                        }
                await session.commit()

            state = {
                "pair": pair,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "threshold": threshold,
                "deterministic": det.to_dict(),
                "llm": verdict.to_dict(),
                "order": order_info,
                "ws_connected": self.ws.is_connected,
            }
            logger.info(
                "%s: det=%s(%d) llm=%s(%d)%s",
                pair,
                det.signal,
                det.confidence,
                verdict.signal,
                verdict.confidence,
                " [FALLBACK]" if verdict.fallback else "",
            )
            return state
        except Exception:  # noqa: BLE001 - une paire ne bloque pas le cycle
            logger.exception("Échec analyse %s", pair)
            return None

    # -- accès état -----------------------------------------------------------
    async def get_latest(self) -> list[dict]:
        async with self._latest_lock:
            return [self._latest[p] for p in self.settings.trading_pairs if p in self._latest]

    async def get_status(self) -> dict:
        return {
            "mode": await self.modes.get_mode(),
            "threshold": await self.modes.get_threshold(),
            "pairs": self.settings.trading_pairs,
            "timeframes": self.settings.trading_timeframes,
            "ws_connected": self.ws.is_connected,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "cycles_count": self._cycles_count,
            "llm_model": self.settings.llm_model,
            "llm_provider": self.settings.llm_provider,
            "llm_enabled": self.settings.llm_enabled,
            "llm_configured": self.settings.llm_configured,
        }

    async def get_history(self, pair: str, limit: int = 50) -> list[dict]:
        async with get_session_factory()() as session:
            res = await session.execute(
                select(AnalysisCycle)
                .where(AnalysisCycle.pair == pair)
                .order_by(desc(AnalysisCycle.time))
                .limit(limit)
            )
            rows = res.scalars().all()
            return [
                {
                    "time": r.time.isoformat(),
                    "pair": r.pair,
                    "det_signal": r.det_signal,
                    "det_score": r.det_score,
                    "llm_signal": r.llm_signal,
                    "llm_score": r.llm_score,
                    "llm_justification": r.llm_justification,
                    "last_price": r.last_price,
                    "volume": r.volume,
                    "mode": r.mode,
                }
                for r in rows
            ]

    async def list_orders(self, status: str | None = None, limit: int = 50) -> list[dict]:
        async with get_session_factory()() as session:
            query = select(PaperOrder).order_by(desc(PaperOrder.time)).limit(limit)
            if status:
                query = (
                    select(PaperOrder)
                    .where(PaperOrder.status == status)
                    .order_by(desc(PaperOrder.time))
                    .limit(limit)
                )
            rows = (await session.execute(query)).scalars().all()
            return [
                {
                    "id": o.id,
                    "time": o.time.isoformat(),
                    "pair": o.pair,
                    "side": o.side,
                    "det_signal": o.det_signal,
                    "det_score": o.det_score,
                    "llm_signal": o.llm_signal,
                    "llm_score": o.llm_score,
                    "llm_justification": o.llm_justification,
                    "price": o.price,
                    "quantity": o.quantity,
                    "notional_usd": o.notional_usd,
                    "status": o.status,
                    "mode_at_creation": o.mode_at_creation,
                    "decided_by": o.decided_by,
                }
                for o in rows
            ]
