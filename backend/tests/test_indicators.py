"""Tests unitaires des indicateurs (numpy pur, déterministes)."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.quant import indicators as ind


def _trend(n=100, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


def test_rsi_uptrend_high():
    assert ind.rsi(_trend(step=1.0)) > 70


def test_rsi_downtrend_low():
    assert ind.rsi(_trend(step=-1.0)) < 30


def test_rsi_flat_neutral():
    assert 40 < ind.rsi([100.0] * 100) <= 100


def test_rsi_insufficient_data_nan():
    assert math.isnan(ind.rsi([1.0, 2.0, 3.0]))


def test_ema_follows_price():
    closes = _trend()
    assert ind.ema(closes, 9) > ind.ema(closes, 21) > closes[0]


def test_bollinger_bands_ordered():
    low, mid, up, pct_b, bw = ind.bollinger(_trend(step=0.5))
    assert low < mid < up
    assert 0.0 <= pct_b <= 1.5
    assert bw > 0


def test_adx_strong_trend():
    closes = _trend(step=2.0)
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    adx_v, plus_di, minus_di = ind.adx(highs, lows, closes)
    assert adx_v > 25
    assert plus_di > minus_di


def test_atr_positive():
    closes = _trend()
    highs = [c + 2 for c in closes]
    lows = [c - 2 for c in closes]
    assert ind.atr(highs, lows, closes) > 0


def test_volume_ratio_baseline():
    vols = [10.0] * 30
    assert abs(ind.volume_ratio(vols) - 1.0) < 1e-9


def test_volume_ratio_spike():
    vols = [10.0] * 29 + [30.0]
    assert ind.volume_ratio(vols, 20) > 2.5
