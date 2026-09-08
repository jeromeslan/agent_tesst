"""Bootstrap REST : chargement de l'historique OHLC initial (Kraken public)."""

from __future__ import annotations

import logging

import aiohttp
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .store import Candle

logger = logging.getLogger(__name__)

# Mapping "BASE/QUOTE" (WS v2) -> paire REST Kraken.
REST_PAIR_ALIASES: dict[str, str] = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "SOL/USD": "SOLUSD",
    "XBT/USD": "XBTUSD",
}


def to_rest_pair(pair: str) -> str:
    if pair in REST_PAIR_ALIASES:
        return REST_PAIR_ALIASES[pair]
    return pair.replace("/", "")


@retry(
    retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    reraise=True,
)
async def fetch_ohlc_history(
    rest_url: str,
    pair: str,
    interval: int,
    timeout: int = 15,
) -> list[Candle]:
    """Récupère l'historique OHLC via GET /0/public/OHLC (720 dernières bougies).

    La dernière bougie renvoyée par Kraken est la bougie en cours (non clôturée)
    — elle est conservée car le WS la mettra à jour en continu.
    """
    params = {"pair": to_rest_pair(pair), "interval": str(interval)}
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        async with session.get(f"{rest_url}/0/public/OHLC", params=params) as resp:
            resp.raise_for_status()
            payload = await resp.json()

    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken REST error for {pair}/{interval}: {errors}")

    result = payload.get("result", {})
    # La clé du résultat est le nom interne Kraken de la paire (ex: XXBTZUSD).
    key = next((k for k in result if k != "last"), None)
    if key is None:
        raise RuntimeError(f"Kraken REST: no OHLC data for {pair}/{interval}")

    candles: list[Candle] = []
    for row in result[key]:
        # [time, open, high, low, close, vwap, volume, count]
        candles.append(
            Candle(
                time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                vwap=float(row[5]),
                volume=float(row[6]),
                trades=int(row[7]),
            )
        )
    candles.sort(key=lambda c: c.time)
    logger.info("REST bootstrap %s M%d : %d bougies", pair, interval, len(candles))
    return candles
