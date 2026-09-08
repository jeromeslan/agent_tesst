"""Indicateurs techniques (numpy pur, sans dépendance TA-Lib).

Conventions : les fonctions prennent des listes/ndarray ordonnés du plus ancien
au plus récent et retournent la valeur de la DERNIÈRE bougie (ou un tuple).
"""

from __future__ import annotations

import numpy as np


def _as_array(values: list[float] | np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=float)


def sma(values: list[float] | np.ndarray, period: int) -> float:
    arr = _as_array(values)
    if len(arr) < period or period <= 0:
        return float("nan")
    return float(arr[-period:].mean())


def ema(values: list[float] | np.ndarray, period: int) -> float:
    arr = _as_array(values)
    if len(arr) < period or period <= 0:
        return float("nan")
    k = 2.0 / (period + 1.0)
    e = float(arr[:period].mean())
    for price in arr[period:]:
        e = float(price) * k + e * (1.0 - k)
    return e


def ema_series(values: list[float] | np.ndarray, period: int) -> np.ndarray:
    """Série EMA complète (Wilder seed = SMA), NaN là où non défini."""
    arr = _as_array(values)
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period or period <= 0:
        return out
    k = 2.0 / (period + 1.0)
    e = float(arr[:period].mean())
    out[period - 1] = e
    for i in range(period, len(arr)):
        e = float(arr[i]) * k + e * (1.0 - k)
        out[i] = e
    return out


def rsi(closes: list[float] | np.ndarray, period: int = 14) -> float:
    """RSI de Wilder (lissage exponentiel des gains/pertes moyens)."""
    arr = _as_array(closes)
    if len(arr) < period + 1:
        return float("nan")
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    for g, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + float(g)) / period
        avg_loss = (avg_loss * (period - 1) + float(loss)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def bollinger(
    closes: list[float] | np.ndarray, period: int = 20, num_std: float = 2.0
) -> tuple[float, float, float, float, float]:
    """Retourne (lower, middle, upper, percent_b, bandwidth)."""
    arr = _as_array(closes)
    if len(arr) < period:
        return (float("nan"),) * 5
    window = arr[-period:]
    middle = float(window.mean())
    std = float(window.std(ddof=0))
    upper = middle + num_std * std
    lower = middle - num_std * std
    last = float(arr[-1])
    width = upper - lower
    percent_b = (last - lower) / width if width > 0 else 0.5
    bandwidth = width / middle if middle != 0 else 0.0
    return (lower, middle, upper, float(percent_b), float(bandwidth))


def atr(
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray,
    closes: list[float] | np.ndarray,
    period: int = 14,
) -> float:
    h = _as_array(highs)
    low = _as_array(lows)
    c = _as_array(closes)
    if len(c) < period + 1:
        return float("nan")
    prev_close = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - low, np.maximum(abs(h - prev_close), abs(low - prev_close)))
    return float(ema(tr.tolist(), period))


def adx(
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray,
    closes: list[float] | np.ndarray,
    period: int = 14,
) -> tuple[float, float, float]:
    """Retourne (ADX, +DI, -DI) selon Wilder."""
    h = _as_array(highs)
    low = _as_array(lows)
    c = _as_array(closes)
    n = len(c)
    if n < 2 * period + 1:
        return (float("nan"), float("nan"), float("nan"))

    up_move = np.diff(h)
    down_move = -np.diff(low)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    prev_close = c[:-1]
    tr = np.maximum(
        h[1:] - low[1:],
        np.maximum(abs(h[1:] - prev_close), abs(low[1:] - prev_close)),
    )

    def _wilder_smooth(series: np.ndarray) -> np.ndarray:
        out = np.full_like(series, np.nan, dtype=float)
        if len(series) < period:
            return out
        acc = float(series[:period].sum())
        out[period - 1] = acc
        for i in range(period, len(series)):
            acc = acc - acc / period + float(series[i])
            out[i] = acc
        return out

    s_tr = _wilder_smooth(tr)
    s_plus = _wilder_smooth(plus_dm)
    s_minus = _wilder_smooth(minus_dm)

    with np.errstate(invalid="ignore", divide="ignore"):
        plus_di = 100.0 * s_plus / s_tr
        minus_di = 100.0 * s_minus / s_tr
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)

    valid = dx[period - 1 :]
    valid = valid[~np.isnan(valid)]
    if len(valid) < period:
        return (float("nan"), float(plus_di[-1]), float(minus_di[-1]))
    adx_value = float(valid[:period].mean())
    for v in valid[period:]:
        adx_value = (adx_value * (period - 1) + float(v)) / period
    return (adx_value, float(plus_di[-1]), float(minus_di[-1]))


def volume_ratio(volumes: list[float] | np.ndarray, period: int = 20) -> float:
    """Volume courant / SMA(volume). >1.5 = climax, <0.5 = désert."""
    arr = _as_array(volumes)
    if len(arr) < period + 1:
        return float("nan")
    mean = float(arr[-period - 1 : -1].mean())
    if mean <= 0:
        return float("nan")
    return float(arr[-1] / mean)
