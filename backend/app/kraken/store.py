"""Stockage mémoire thread-safe des bougies OHLC par (paire, timeframe)."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class Candle:
    time: int  # timestamp d'ouverture (secondes)
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    trades: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class CandleStore:
    """Conserve les N dernières bougies par (paire, timeframe)."""

    def __init__(self, maxlen: int = 720) -> None:
        self._maxlen = maxlen
        self._data: dict[tuple[str, int], deque[Candle]] = {}
        self._lock = asyncio.Lock()

    def _key(self, pair: str, timeframe: int) -> tuple[str, int]:
        return (pair, timeframe)

    async def replace(self, pair: str, timeframe: int, candles: list[Candle]) -> None:
        async with self._lock:
            dq: deque[Candle] = deque(candles[-self._maxlen :], maxlen=self._maxlen)
            self._data[self._key(pair, timeframe)] = dq

    async def upsert_live(self, pair: str, timeframe: int, candle: Candle) -> bool:
        """Insère/met à jour la bougie live. Retourne True si NOUVELLE bougie."""
        async with self._lock:
            dq = self._data.setdefault(
                self._key(pair, timeframe), deque(maxlen=self._maxlen)
            )
            if dq and dq[-1].time == candle.time:
                dq[-1] = candle
                return False
            if dq and candle.time < dq[-1].time:
                return False  # donnée périmée
            dq.append(candle)
            return True

    async def get_candles(self, pair: str, timeframe: int) -> list[Candle]:
        async with self._lock:
            return list(self._data.get(self._key(pair, timeframe), []))

    async def count(self, pair: str, timeframe: int) -> int:
        async with self._lock:
            return len(self._data.get(self._key(pair, timeframe), []))

    async def last_close(self, pair: str, timeframe: int = 1) -> float | None:
        async with self._lock:
            dq = self._data.get(self._key(pair, timeframe))
            return dq[-1].close if dq else None

    async def last_volume(self, pair: str, timeframe: int = 1) -> float | None:
        async with self._lock:
            dq = self._data.get(self._key(pair, timeframe))
            return dq[-1].volume if dq else None
