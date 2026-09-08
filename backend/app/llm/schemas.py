"""Schéma strict du verdict LLM (Structured Outputs / JSON Mode)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VerdictPayload(BaseModel):
    """Payload JSON strict attendu du LLM."""

    signal: Literal["SHORT", "HOLD", "LONG"] = Field(
        description="Signal ajusté par le LLM."
    )
    confidence: int = Field(
        ge=0, le=100, description="Score de confiance final (0-100)."
    )
    justification: str = Field(
        max_length=500,
        description="Courte justification textuelle (1-2 phrases).",
    )


# JSON Schema envoyé à l'API via `response_format` (Structured Outputs).
VERDICT_JSON_SCHEMA: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "trading_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "signal": {
                    "type": "string",
                    "enum": ["SHORT", "HOLD", "LONG"],
                    "description": "Signal ajusté par le LLM.",
                },
                "confidence": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Score de confiance final (0-100).",
                },
                "justification": {
                    "type": "string",
                    "description": "Courte justification (1-2 phrases, en français).",
                },
            },
            "required": ["signal", "confidence", "justification"],
            "additionalProperties": False,
        },
    },
}
