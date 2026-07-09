"""Application configuration, loaded from environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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
    # Extra CORS origins (comma-separated), e.g. your Vercel domain(s).
    extra_cors_origins: str = ""

    # Database / Redis
    # Supabase Postgres. Use the *pooler* URL (port 6543) for the app at runtime,
    # and the *direct* URL (port 5432) for Alembic migrations. asyncpg driver.
    database_url: str = "postgresql+asyncpg://pulse:pulse@localhost:5432/pulse"
    # Set true when database_url points at Supabase's transaction pooler (pgBouncer).
    db_use_pgbouncer: bool = False
    # asyncpg SSL mode: "" (off, local) | "require" (Supabase) | "verify-full".
    db_ssl: str = ""
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Supabase Auth. The frontend logs in with the anon key; the backend verifies
    # the resulting JWT. HS256 uses the legacy JWT secret; asymmetric (RS256/ES256)
    # projects are verified via the JWKS endpoint automatically.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_service_role_key: str = ""  # server-only admin ops (optional)

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

    @property
    def llm_configured(self) -> bool:
        return bool(self.token_router_api_key or self.anthropic_api_key)

    # Competitor research uses Perplexity for grounded web results and DeepSeek
    # for strict structured parsing. Google Maps is used only for geocoding.
    strict_free_tier: bool = True
    google_maps_api_key: str = ""

    # Competitor price source discovery and extraction.
    # Perplexity Search returns structured web results; TokenMart provides the
    # OpenAI-compatible gateway used to call the DeepSeek model.
    perplexity_api_key: str = ""
    perplexity_search_base_url: str = "https://api.perplexity.ai"
    enable_perplexity_search: bool = True
    perplexity_search_country: str = "US"
    perplexity_search_context_size: str = "high"
    perplexity_max_results: int = 5
    perplexity_max_queries_per_competitor: int = 3
    tokenmart_api_key: str = ""
    tokenmart_base_url: str = "https://model.service-inference.ai/v1"
    tokenmart_model: str = "deepseek-v4-flash"
    # Legacy direct-provider/gateway settings remain as fallbacks while existing
    # deployments migrate to TOKENMART_* variables.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    enable_deepseek_extraction: bool = True
    deepseek_use_token_router: bool = False

    @property
    def auth_configured(self) -> bool:
        """True once Supabase Auth is wired (URL is enough to verify via JWKS)."""
        return bool(self.supabase_url)

    # Email / SMS
    resend_api_key: str = ""
    resend_from_email: str = "hello@example.com"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # Square OAuth app (Developer Dashboard → your app). Enables "Connect with Square".
    square_app_id: str = ""
    square_app_secret: str = ""
    square_environment: Literal["sandbox", "production"] = "sandbox"

    # Stripe Connect platform (Dashboard → Settings → Connect). Enables
    # "Connect with Stripe"; token exchange authenticates with stripe_secret_key.
    stripe_connect_client_id: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_growth: str = ""
    stripe_price_pro: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        """Allowed browser origins: the frontend origin plus any extras from env."""
        origins = {self.frontend_origin}
        origins.update(o.strip() for o in self.extra_cors_origins.split(",") if o.strip())
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
