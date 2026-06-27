"""Application configuration, loaded from environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:5173"

    # Database / Redis
    database_url: str = "postgresql+asyncpg://pulse:pulse@localhost:5432/pulse"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Supabase Auth
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""

    # Secrets at rest
    fernet_key: str = ""

    # Token Router — every LLM ("AAM") call is routed through this gateway.
    # Protocol selects how we speak to it: "openai" => /chat/completions,
    # "anthropic" => /messages. Direct Anthropic is only a no-router fallback.
    token_router_api_key: str = ""
    token_router_base_url: str = ""  # e.g. https://api.tokenrouter.io/v1
    token_router_model: str = "claude-sonnet-4-6"
    token_router_protocol: Literal["openai", "anthropic"] = "openai"

    # Anthropic (fallback only when Token Router is not configured)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Convex — auth backend (multi-tenant: each business is a tenant)
    convex_url: str = ""  # deployment URL, e.g. https://your-app.convex.cloud
    convex_api_key: str = ""  # shared secret authorizing API -> Convex calls
    # Backend-issued session JWT signed after Convex verifies credentials.
    auth_jwt_secret: str = "dev-insecure-change-me-please-set-a-real-secret"
    auth_jwt_ttl_hours: int = 24 * 7

    @property
    def llm_configured(self) -> bool:
        return bool(self.token_router_api_key or self.anthropic_api_key)

    # Email / SMS
    resend_api_key: str = ""
    resend_from_email: str = "hello@example.com"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # Square
    square_app_id: str = ""
    square_app_secret: str = ""
    square_environment: Literal["sandbox", "production"] = "sandbox"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_growth: str = ""
    stripe_price_pro: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
