"""Configuration centrale (pydantic-settings, chargée depuis l'env / .env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Base de données -------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://trader:trader_secret@localhost:5432/trading",
        description="URL async SQLAlchemy (TimescaleDB en prod, SQLite en dev local).",
    )

    # --- Trading ---------------------------------------------------------
    trading_pairs: list[str] = Field(default=["BTC/USD", "ETH/USD", "SOL/USD"])
    trading_timeframes: list[int] = Field(default=[1, 5, 15])
    execution_mode: Literal["FULL_AUTO", "HITM"] = Field(default="HITM")
    confidence_threshold: int = Field(default=70, ge=0, le=100)
    paper_notional_usd: float = Field(default=100.0, gt=0)
    pipeline_interval_seconds: int = Field(default=60, ge=10)

    # --- Kraken ----------------------------------------------------------
    kraken_rest_url: str = Field(default="https://api.kraken.com")
    kraken_ws_url: str = Field(default="wss://ws.kraken.com/v2")
    kraken_rest_timeout: int = Field(default=15)
    kraken_history_candles: int = Field(default=300, ge=60, le=720)

    # --- Agent LLM (appel RÉEL via SDK OpenAI) ---------------------------
    # Le SDK OpenAI est utilisé tel quel ; `llm_base_url` permet de pointer
    # vers tout endpoint compatible OpenAI (gateway arena.ai, OpenRouter,
    # LiteLLM...) donnant accès au set de modèles arena.ai
    # (GPT, Claude, Gemini, Grok, Qwen, Kimi...).
    llm_enabled: bool = Field(default=True)
    llm_provider: str = Field(default="openai")
    llm_model: str = Field(default="gpt-4o")
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="")
    llm_timeout_seconds: int = Field(default=30, ge=5, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    # --- Backend ----------------------------------------------------------
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    @field_validator("trading_pairs", mode="before")
    @classmethod
    def _split_pairs(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @field_validator("trading_timeframes", mode="before")
    @classmethod
    def _split_timeframes(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(t.strip()) for t in v.split(",") if t.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_configured(self) -> bool:
        return self.llm_enabled and bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
