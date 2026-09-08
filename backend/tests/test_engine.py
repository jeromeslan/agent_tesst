"""Tests du moteur déterministe (signaux sur tendances synthétiques)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.kraken.store import Candle, CandleStore
from app.quant.engine import DeterministicEngine


def _candles(n, start, step, vol=10.0):
    out = []
    price = start
    for i in range(n):
        price += step
        out.append(
            Candle(
                time=1_700_000_000 + i * 60,
                open=price - step,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=vol,
            )
        )
    return out


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_strong_uptrend_is_long():
    store = CandleStore()
    _run(store.replace("BTC/USD", 1, _candles(120, 50000, 15.0)))
    _run(store.replace("BTC/USD", 5, _candles(120, 50000, 15.0)))
    _run(store.replace("BTC/USD", 15, _candles(120, 50000, 15.0)))
    engine = DeterministicEngine(store)
    res = _run(engine.analyze("BTC/USD", [1, 5, 15]))
    assert res.signal == "LONG", res.to_dict()
    assert res.confidence > 0


def test_strong_downtrend_is_short():
    store = CandleStore()
    _run(store.replace("BTC/USD", 1, _candles(120, 50000, -15.0)))
    _run(store.replace("BTC/USD", 5, _candles(120, 50000, -15.0)))
    _run(store.replace("BTC/USD", 15, _candles(120, 50000, -15.0)))
    engine = DeterministicEngine(store)
    res = _run(engine.analyze("BTC/USD", [1, 5, 15]))
    assert res.signal == "SHORT", res.to_dict()


def test_insufficient_history_is_hold():
    store = CandleStore()
    engine = DeterministicEngine(store)
    res = _run(engine.analyze("BTC/USD", [1, 5, 15]))
    assert res.signal == "HOLD"
    assert res.confidence == 0
