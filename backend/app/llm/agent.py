"""Agent LLM — APPEL RÉEL via le SDK `openai` (jamais mocké).

Compatibilité arena.ai : le client OpenAI accepte une `base_url` personnalisée,
ce qui permet d'utiliser — sans changer une ligne de code — tout endpoint
compatible OpenAI donnant accès au set de modèles arena.ai
(GPT, Claude, Gemini, Grok, Qwen, Kimi/Moonshot...) :

    LLM_BASE_URL=https://<gateway-compatible-openai>/v1
    LLM_MODEL=<modèle arena.ai, ex: gpt-4o>
    LLM_API_KEY=<clé>

Par défaut : OpenAI direct avec `gpt-4o` (cf. spec du PoC).

Stratégie de fiabilité :
  1. Structured Outputs (`response_format` json_schema strict) ;
  2. repli JSON Mode (`response_format={"type": "json_object"}`) si le
     endpoint/gateway ne supporte pas les schémas stricts ;
  3. extraction JSON tolérante depuis le contenu texte en dernier recours.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from openai import AsyncOpenAI

from ..config import get_settings
from ..quant.engine import DeterministicResult
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import VERDICT_JSON_SCHEMA, VerdictPayload

logger = logging.getLogger(__name__)

LLMSignal = Literal["SHORT", "HOLD", "LONG"]

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(slots=True)
class LLMVerdict:
    signal: str  # SHORT | HOLD | LONG
    confidence: int  # 0..100
    justification: str
    model: str
    provider: str
    latency_ms: int
    fallback: bool = False  # True si le LLM n'a pas pu être joint
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class LLMAgent:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        # Client officiel OpenAI — `base_url` optionnelle (gateway arena.ai, etc.)
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key or "missing-key",
            base_url=settings.llm_base_url or None,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    @property
    def model_name(self) -> str:
        return self._settings.llm_model

    # -- API principale ---------------------------------------------------
    async def review(self, result: DeterministicResult) -> LLMVerdict:
        """Envoie l'état déterministe au LLM et retourne un verdict strict.

        Ne lève PAS : en cas d'échec (clé manquante, réseau, quota...),
        retourne un verdict de repli calqué sur le déterministe avec
        `fallback=True` pour ne jamais bloquer le pipeline.
        """
        settings = self._settings
        if not settings.llm_enabled:
            return self._fallback(result, "LLM désactivé par configuration.")
        if not settings.llm_api_key:
            return self._fallback(result, "Clé LLM manquante (LLM_API_KEY).")

        user_prompt = build_user_prompt(result)
        started = time.perf_counter()
        try:
            payload, raw = await self._call_structured(user_prompt)
            verdict = VerdictPayload.model_validate(payload)
            latency = int((time.perf_counter() - started) * 1000)
            logger.info(
                "%s: LLM %s -> %s (%d) en %dms",
                result.pair,
                settings.llm_model,
                verdict.signal,
                verdict.confidence,
                latency,
            )
            return LLMVerdict(
                signal=verdict.signal,
                confidence=verdict.confidence,
                justification=verdict.justification,
                model=settings.llm_model,
                provider=settings.llm_provider,
                latency_ms=latency,
                fallback=False,
                raw=raw,
            )
        except Exception as exc:  # noqa: BLE001 - robustesse pipeline
            latency = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "%s: appel LLM impossible (%s) — repli déterministe.",
                result.pair,
                exc,
            )
            v = self._fallback(result, f"LLM indisponible ({exc}).")
            v.latency_ms = latency
            return v

    # -- Appels API ---------------------------------------------------------
    async def _call_structured(self, user_prompt: str) -> tuple[dict, dict]:
        """Tente Structured Outputs puis JSON Mode. Retourne (payload, raw)."""
        settings = self._settings
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        # 1) Structured Outputs (schéma strict)
        try:
            completion = await self._client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=settings.llm_temperature,
                max_tokens=300,
                response_format=VERDICT_JSON_SCHEMA,  # type: ignore[arg-type]
            )
            return self._extract(completion)
        except Exception as exc:  # noqa: BLE001 - repli JSON Mode
            logger.debug("Structured Outputs indisponible (%s), repli JSON Mode.", exc)

        # 2) JSON Mode simple (compat gateways OpenAI-compatibles)
        completion = await self._client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=settings.llm_temperature,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        return self._extract(completion)

    @staticmethod
    def _extract(completion: Any) -> tuple[dict, dict]:
        raw = completion.model_dump() if hasattr(completion, "model_dump") else {}
        try:
            content = completion.choices[0].message.content or ""
        except (AttributeError, IndexError, KeyError) as exc:
            raise ValueError(f"Réponse LLM sans contenu : {exc}") from exc
        payload = _parse_json_strict(content)
        return payload, {
            "content": content,
            "model": getattr(completion, "model", None),
            "usage": raw.get("usage") if isinstance(raw, dict) else None,
            "id": raw.get("id") if isinstance(raw, dict) else None,
        }

    # -- Repli ---------------------------------------------------------------
    def _fallback(self, result: DeterministicResult, reason: str) -> LLMVerdict:
        mapping = {"LONG": "LONG", "SHORT": "SHORT", "HOLD": "HOLD"}
        return LLMVerdict(
            signal=mapping.get(result.signal, "HOLD"),
            confidence=min(result.confidence, 50),
            justification=f"[Repli déterministe] {reason} Signal repris du moteur.",
            model=self._settings.llm_model,
            provider=self._settings.llm_provider,
            latency_ms=0,
            fallback=True,
            raw={"fallback_reason": reason},
        )


def _parse_json_strict(content: str) -> dict:
    """Parse le JSON renvoyé par le LLM (tolère un encadrement ```json)."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if not match:
            raise ValueError(f"Réponse LLM non-JSON : {content[:200]!r}")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError(f"Réponse LLM inattendue : {content[:200]!r}")
    return data
