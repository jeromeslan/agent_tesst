"""Gestion du mode d'exécution global : FULL_AUTO | HITM."""

from __future__ import annotations

import asyncio
from typing import Literal

ExecutionMode = Literal["FULL_AUTO", "HITM"]


class ModeManager:
    """État global thread-safe (basculable via API)."""

    def __init__(self, initial: ExecutionMode = "HITM", threshold: int = 70) -> None:
        self._mode: ExecutionMode = initial
        self._threshold = threshold
        self._lock = asyncio.Lock()

    async def get_mode(self) -> ExecutionMode:
        async with self._lock:
            return self._mode

    async def set_mode(self, mode: ExecutionMode) -> ExecutionMode:
        if mode not in ("FULL_AUTO", "HITM"):
            raise ValueError(f"Mode inconnu : {mode!r}")
        async with self._lock:
            self._mode = mode
            return self._mode

    async def get_threshold(self) -> int:
        async with self._lock:
            return self._threshold

    async def set_threshold(self, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError("Le seuil doit être entre 0 et 100.")
        async with self._lock:
            self._threshold = value
            return self._threshold
