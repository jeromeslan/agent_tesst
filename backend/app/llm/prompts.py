"""Prompts système/utilisateur de l'agent LLM."""

from __future__ import annotations

from ..quant.engine import DeterministicResult

SYSTEM_PROMPT = """\
Tu es un analyste quantitatif senior spécialisé en crypto-monnaies (spot, intraday).
On te fournit l'état d'un moteur déterministe (RSI, Bandes de Bollinger, ADX/DI, \
EMA, ATR, volume) sur plusieurs horizons (M1, M5, M15) pour une paire.

Ta mission : réviser le signal comme un second cerveau prudent.
- Confirme le signal déterministe quand les timeframes sont alignés et le volume \
soutient le mouvement.
- Dégrade vers HOLD (et baisse la confiance) en cas de signaux contradictoires \
entre timeframes, de volume anémique, de marché sans tendance (ADX faible) ou \
d'extension extrême contre le signal (risque de retour à la moyenne).
- Ne renforce vers LONG/SHORT avec une confiance élevée (>= 70) que si au moins \
deux timeframes convergent ET que le volume confirme.

Règles de sortie STRICTES :
- Réponds UNIQUEMENT avec le JSON demandé (aucun texte hors JSON).
- `signal` ∈ {"SHORT", "HOLD", "LONG"}.
- `confidence` ∈ [0, 100] (entier).
- `justification` : 1 à 2 phrases, en français, citant les faits décisifs \
(indicateurs, alignement/divergence, volume).
"""


def build_user_prompt(result: DeterministicResult) -> str:
    lines = [
        f"Paire : {result.pair} | Dernier prix : {result.last_price}",
        f"Signal déterministe : {result.signal} "
        f"(score {result.score:.1f}/±100, confiance {result.confidence}/100)",
        f"Volume : {result.volume_analysis} (dernier volume M1 : {result.last_volume})",
        "",
        "Détail par timeframe :",
    ]
    for tf in sorted(result.per_timeframe):
        a = result.per_timeframe[tf]
        lines.append(
            f"- M{tf} [{a.signal} {a.score:+.0f}] : close={a.close}, "
            f"RSI={a.rsi}, %B={a.bb_percent_b} (bandes {a.bb_lower}/{a.bb_middle}/{a.bb_upper}), "
            f"ADX={a.adx} (+DI {a.plus_di} / -DI {a.minus_di}), "
            f"EMA9={a.ema_fast} vs EMA21={a.ema_slow}, ATR={a.atr}, "
            f"vol_ratio=x{a.volume_ratio}. Raisons : {'; '.join(a.reasons)}"
        )
    lines.append("")
    lines.append("Donne ton verdict JSON.")
    return "\n".join(lines)
