"""Moteur déterministe : indicateurs -> signal + score + analyse volume.

Pondération multi-timeframe (biais long-terme) :
    M1 = 0.20, M5 = 0.30, M15 = 0.50 (normalisée si un timeframe manque).
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field

from ..kraken.store import CandleStore
from . import indicators as ind

logger = logging.getLogger(__name__)

SignalType = str  # "LONG" | "SHORT" | "HOLD"

TF_WEIGHTS: dict[int, float] = {1: 0.20, 5: 0.30, 15: 0.50}

LONG_THRESHOLD = 15.0
SHORT_THRESHOLD = -15.0


def _safe(value: float, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return default
    return float(value)


@dataclass(slots=True)
class TimeframeAnalysis:
    timeframe: int
    close: float
    rsi: float
    bb_lower: float
    bb_middle: float
    bb_upper: float
    bb_percent_b: float
    bb_bandwidth: float
    adx: float
    plus_di: float
    minus_di: float
    ema_fast: float
    ema_slow: float
    atr: float
    volume: float
    volume_ratio: float
    score: float  # -100 .. +100
    signal: SignalType
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class DeterministicResult:
    pair: str
    signal: SignalType
    score: float  # -100 .. +100
    confidence: int  # 0 .. 100
    volume_analysis: str
    last_price: float
    last_volume: float
    per_timeframe: dict[int, TimeframeAnalysis]

    def to_dict(self) -> dict:
        return {
            "pair": self.pair,
            "signal": self.signal,
            "score": round(self.score, 2),
            "confidence": self.confidence,
            "volume_analysis": self.volume_analysis,
            "last_price": self.last_price,
            "last_volume": self.last_volume,
            "per_timeframe": {str(k): v.to_dict() for k, v in self.per_timeframe.items()},
        }


class DeterministicEngine:
    def __init__(self, store: CandleStore) -> None:
        self._store = store

    async def analyze(self, pair: str, timeframes: list[int]) -> DeterministicResult:
        per_tf: dict[int, TimeframeAnalysis] = {}
        for tf in timeframes:
            candles = await self._store.get_candles(pair, tf)
            if len(candles) < 40:
                logger.debug(
                    "%s M%d: historique insuffisant (%d bougies), timeframe ignoré.",
                    pair,
                    tf,
                    len(candles),
                )
                continue
            per_tf[tf] = self._analyze_timeframe(tf, candles)

        if not per_tf:
            return DeterministicResult(
                pair=pair,
                signal="HOLD",
                score=0.0,
                confidence=0,
                volume_analysis="Historique insuffisant — pas de lecture volume.",
                last_price=0.0,
                last_volume=0.0,
                per_timeframe={},
            )

        total_w = sum(TF_WEIGHTS.get(tf, 0.2) for tf in per_tf)
        score = sum(a.score * TF_WEIGHTS.get(tf, 0.2) for tf, a in per_tf.items()) / total_w
        signal: SignalType = (
            "LONG" if score >= LONG_THRESHOLD else "SHORT" if score <= SHORT_THRESHOLD else "HOLD"
        )

        # Confiance : magnitude du score + bonus tendance (ADX M15) + bonus volume.
        ref = per_tf.get(15) or per_tf.get(5) or next(iter(per_tf.values()))
        confidence = min(100, int(abs(score) * 0.9))
        if _safe(ref.adx) >= 25:
            confidence = min(100, confidence + 10)
        if _safe(ref.volume_ratio) >= 1.2:
            confidence = min(100, confidence + 5)
        if signal == "HOLD":
            confidence = min(confidence, 55)

        volume_analysis = self._describe_volume(ref)
        return DeterministicResult(
            pair=pair,
            signal=signal,
            score=score,
            confidence=confidence,
            volume_analysis=volume_analysis,
            last_price=ref.close,
            last_volume=ref.volume,
            per_timeframe=per_tf,
        )

    # -- analyse d'un timeframe -------------------------------------------
    def _analyze_timeframe(self, timeframe: int, candles: list) -> TimeframeAnalysis:
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]

        rsi_v = _safe(ind.rsi(closes, 14), 50.0)
        bb_low, bb_mid, bb_up, pct_b, bw = ind.bollinger(closes, 20, 2.0)
        adx_v, plus_di, minus_di = ind.adx(highs, lows, closes, 14)
        ema_fast = _safe(ind.ema(closes, 9))
        ema_slow = _safe(ind.ema(closes, 21))
        atr_v = _safe(ind.atr(highs, lows, closes, 14))
        vol_ratio = _safe(ind.volume_ratio(volumes, 20), 1.0)

        votes: list[tuple[float, str]] = []

        # Direction de la tendance (calculée EN PREMIER) : en tendance forte,
        # les oscillateurs contrarians sont atténués — un marché en tendance
        # peut rester "suracheté"/"survendu" longtemps (classique).
        adx_v = _safe(adx_v)
        plus_di = _safe(plus_di)
        minus_di = _safe(minus_di)
        strong_trend = adx_v >= 25
        trend_dir = 0  # +1 haussier, -1 baissier, 0 range
        if strong_trend:
            trend_dir = 1 if plus_di > minus_di else (-1 if minus_di > plus_di else 0)

        def _vote(value: float, reason: str) -> None:
            # Atténue les votes CONTRARIANS à une tendance forte (x0.3).
            if strong_trend and trend_dir != 0 and (value > 0) != (trend_dir > 0):
                value *= 0.3
                reason += " [atténué : tendance forte]"
            votes.append((value, reason))

        # 1) RSI : surachat/survente (poids 30)
        if rsi_v <= 25:
            _vote(30, f"RSI {rsi_v:.1f} en survente extrême")
        elif rsi_v < 35:
            _vote(18, f"RSI {rsi_v:.1f} en survente")
        elif rsi_v > 75:
            _vote(-30, f"RSI {rsi_v:.1f} en surachat extrême")
        elif rsi_v > 65:
            _vote(-18, f"RSI {rsi_v:.1f} en surachat")
        elif rsi_v >= 55:
            _vote(8, f"RSI {rsi_v:.1f} haussier")
        elif rsi_v <= 45:
            _vote(-8, f"RSI {rsi_v:.1f} baissier")

        # 2) Bollinger %B (poids 25)
        pct_b = _safe(pct_b, 0.5)
        if pct_b <= 0.0:
            _vote(25, "Prix sous la bande basse (extension vendeuse)")
        elif pct_b < 0.2:
            _vote(14, "Prix proche de la bande basse")
        elif pct_b >= 1.0:
            _vote(-25, "Prix au-dessus de la bande haute (extension acheteuse)")
        elif pct_b > 0.8:
            _vote(-14, "Prix proche de la bande haute")

        # 3) Tendance ADX/DI (poids 25) — jamais atténuée (c'est la référence)
        if adx_v >= 25:
            if plus_di > minus_di:
                votes.append((25, f"Tendance haussière forte (ADX {adx_v:.1f})"))
            else:
                votes.append((-25, f"Tendance baissière forte (ADX {adx_v:.1f})"))
        elif adx_v >= 18:
            if plus_di > minus_di:
                votes.append((10, f"Tendance haussière naissante (ADX {adx_v:.1f})"))
            else:
                votes.append((-10, f"Tendance baissière naissante (ADX {adx_v:.1f})"))
        else:
            votes.append((0, f"Pas de tendance (ADX {adx_v:.1f}) — range probable"))

        # 4) EMA 9/21 (poids 15) — momentum, jamais atténué
        if ema_fast > ema_slow:
            votes.append((15, "EMA9 > EMA21 (momentum haussier)"))
        elif ema_fast < ema_slow:
            votes.append((-15, "EMA9 < EMA21 (momentum baissier)"))

        # 5) Volume : confirme ou affaiblit (modulateur, pas un vote pur)
        if vol_ratio >= 2.0:
            votes.append((5 if sum(v for v, _ in votes) >= 0 else -5,
                          f"Climax volume x{vol_ratio:.1f} — mouvement soutenu"))
        elif vol_ratio <= 0.4:
            votes.append((0, f"Volume anémique x{vol_ratio:.2f} — signal fragile"))

        raw = sum(v for v, _ in votes)
        score = max(-100.0, min(100.0, raw))
        signal: SignalType = (
            "LONG" if score >= LONG_THRESHOLD else "SHORT" if score <= SHORT_THRESHOLD else "HOLD"
        )
        return TimeframeAnalysis(
            timeframe=timeframe,
            close=float(closes[-1]),
            rsi=round(rsi_v, 2),
            bb_lower=round(_safe(bb_low), 4),
            bb_middle=round(_safe(bb_mid), 4),
            bb_upper=round(_safe(bb_up), 4),
            bb_percent_b=round(pct_b, 3),
            bb_bandwidth=round(_safe(bw), 4),
            adx=round(adx_v, 2),
            plus_di=round(plus_di, 2),
            minus_di=round(minus_di, 2),
            ema_fast=round(ema_fast, 4),
            ema_slow=round(ema_slow, 4),
            atr=round(atr_v, 4),
            volume=float(volumes[-1]),
            volume_ratio=round(vol_ratio, 2),
            score=round(score, 2),
            signal=signal,
            reasons=[r for _, r in votes],
        )

    @staticmethod
    def _describe_volume(ref: TimeframeAnalysis) -> str:
        r = ref.volume_ratio
        if r >= 2.0:
            return f"Climax acheteur/vendeur (x{r:.1f} vs moyenne 20) — conviction forte."
        if r >= 1.2:
            return f"Volume soutenu (x{r:.1f}) — le mouvement est accompagné."
        if r >= 0.8:
            return f"Volume neutre (x{r:.1f}) — pas de confirmation ni d'alerte."
        if r >= 0.4:
            return f"Volume faible (x{r:.1f}) — signal à considérer avec prudence."
        return f"Volume anémique (x{r:.1f}) — marché désert, signal peu fiable."
