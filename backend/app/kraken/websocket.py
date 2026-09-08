"""Client WebSocket public Kraken (v2, canal OHLC) avec reconnexion robuste."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from .store import Candle

logger = logging.getLogger(__name__)

# Callback : (paire, timeframe_minutes, bougie, is_new_candle) -> None
CandleCallback = Callable[[str, int, Candle, bool], Awaitable[None]]


class KrakenWSClient:
    """Écoute les clôtures OHLC en direct sur Kraken WS v2.

    - Souscription multi-paires × multi-intervalles (M1/M5/M15).
    - Reconnexion avec backoff exponentiel + jitter en cas de coupure.
    - Ping/pong applicatif pour détecter les connexions mortes.
    """

    def __init__(
        self,
        ws_url: str,
        pairs: list[str],
        timeframes: list[int],
        on_candle: CandleCallback,
        ping_interval: int = 20,
        ping_timeout: int = 20,
    ) -> None:
        self._ws_url = ws_url
        self._pairs = pairs
        self._timeframes = timeframes
        self._on_candle = on_candle
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._connected = asyncio.Event()
        self._last_seen_candle: dict[tuple[str, int], int] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run_forever(), name="kraken-ws")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._connected.clear()

    # -- boucle principale -------------------------------------------------
    async def _run_forever(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._run_once()
                attempt = 0  # sortie propre -> reset du compteur
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - robustesse réseau
                attempt += 1
                delay = min(2**attempt, 60) + random.uniform(0, 2)
                logger.warning(
                    "Kraken WS déconnecté (%s). Reconnexion dans %.1fs (tentative %d).",
                    exc,
                    delay,
                    attempt,
                )
                self._connected.clear()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    break  # stop demandé pendant l'attente
                except TimeoutError:
                    continue

    async def _run_once(self) -> None:
        logger.info("Connexion Kraken WS : %s", self._ws_url)
        async with websockets.connect(
            self._ws_url,
            ping_interval=self._ping_interval,
            ping_timeout=self._ping_timeout,
            max_size=2**20,
        ) as ws:
            await self._subscribe(ws)
            self._connected.set()
            logger.info(
                "Kraken WS connecté — paires=%s timeframes=%s",
                self._pairs,
                self._timeframes,
            )
            async for raw in ws:
                if self._stop.is_set():
                    break
                await self._handle_message(raw)

    async def _subscribe(
        self, ws: websockets.WebSocketClientProtocol
    ) -> None:
        # Une souscription par intervalle (le canal OHLC v2 prend 1 intervalle).
        for interval in self._timeframes:
            msg = {
                "method": "subscribe",
                "params": {
                    "channel": "ohlc",
                    "symbol": self._pairs,
                    "interval": interval,
                    "snapshot": False,
                },
            }
            await ws.send(json.dumps(msg))
            logger.debug("WS subscribe: %s", msg)

    # -- parsing ------------------------------------------------------------
    async def _handle_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return

        if not isinstance(msg, dict):
            return
        if msg.get("channel") != "ohlc" or msg.get("type") != "update":
            # status / heartbeat / subscriptionStatus : ignorés (log debug)
            if msg.get("method") == "subscribe" and not msg.get("success", True):
                logger.error("Échec souscription WS : %s", msg)
            return

        for entry in msg.get("data", []) or []:
            try:
                symbol: str = entry["symbol"]  # ex: "BTC/USD"
                interval: int = int(entry["interval"])
                begin = entry["interval_begin"]  # ISO ou timestamp selon version
                candle = Candle(
                    time=self._parse_time(begin),
                    open=float(entry["open"]),
                    high=float(entry["high"]),
                    low=float(entry["low"]),
                    close=float(entry["close"]),
                    volume=float(entry.get("volume", 0.0)),
                    vwap=float(entry.get("vwap", 0.0)),
                    trades=int(entry.get("trades", 0)),
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.debug("Message OHLC ignoré (%s): %s", exc, entry)
                continue

            key = (symbol, interval)
            is_new = self._last_seen_candle.get(key) != candle.time
            self._last_seen_candle[key] = candle.time
            try:
                await self._on_candle(symbol, interval, candle, is_new)
            except Exception as exc:  # noqa: BLE001 - ne jamais tuer la boucle WS
                logger.exception("Erreur callback bougie %s M%d: %s", symbol, interval, exc)

    @staticmethod
    def _parse_time(value: object) -> int:
        """Kraken v2 envoie `interval_begin` en ISO-8601 (ou epoch en secondes)."""
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if text[:1].isdigit() and "T" not in text and "-" not in text[:5]:
                return int(float(text))
            from datetime import datetime

            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return int(dt.timestamp())
        raise ValueError(f"format de temps OHLC inconnu: {value!r}")
