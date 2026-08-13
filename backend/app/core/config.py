"""Application configuration, loaded from environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
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
    # Commit this build came from, baked in by the Docker build (see Dockerfile)
    # and reported at /api/health so a rollout can be verified from outside.
    # Empty when running from source.
    app_revision: str = ""
    log_level: str = "INFO"
    api_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:5173"
    # Extra CORS origins (comma-separated), e.g. your Vercel domain(s).
    extra_cors_origins: str = ""

    # Database / Redis
    # Supabase Postgres. Use the *pooler* URL (port 6543) for the app at runtime,
    # and the *direct* URL (port 5432) for Alembic migrations. asyncpg driver.
    database_url: str = "postgresql+asyncpg://pulse:pulse@localhost:5432/pulse"
    # Optional direct Postgres URL used by Alembic. Runtime traffic can continue
    # through a transaction pooler while schema changes use port 5432 directly.
    database_migration_url: str = ""
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

    # Local dev only: serve the built-in demo tenant instead of requiring a Bearer
    # token, even though Supabase *is* configured in .env. Exists because the
    # alternative — blanking SUPABASE_URL for one process — isn't portable:
    # PowerShell deletes an env var when you assign "" to it, so the override
    # silently falls back to the .env value and every request 401s. Rejected
    # outright when ENVIRONMENT=production (see _validate_production_secrets).
    auth_disabled: bool = False

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
    def effective_database_migration_url(self) -> str:
        return self.database_migration_url or self.database_url

    @property
    def llm_configured(self) -> bool:
        return bool(self.token_router_api_key or self.anthropic_api_key)

    # Competitor research uses Google Places for authoritative local-business
    # discovery and Perplexity Sonar for grounded research and structured output.
    # Pricing pipeline v2. ``strict_free_tier`` remains accepted for legacy
    # deployments, but quota, cache, and provider budgets are now independent.
    pricing_pipeline_v2_enabled: bool = True
    pricing_monitoring_enabled: bool = False
    pricing_daily_fresh_run_limit: int = 10
    pricing_complete_cache_minutes: int = 120
    pricing_no_evidence_cache_minutes: int = 30
    pricing_max_provider_cost_usd: float = 0.10
    pricing_max_competitors_per_run: int = 4
    pricing_max_ai_fallbacks_per_run: int = 2
    pricing_max_content_fallbacks_per_run: int = 1
    pricing_max_geocoding_requests_per_run: int = 1
    pricing_place_provider: Literal["google_places", "foursquare"] = "google_places"
    pricing_search_provider: Literal["perplexity", "tavily", "exa"] = "perplexity"
    pricing_content_fallback: Literal["none", "tavily", "exa", "firecrawl"] = "none"
    pricing_extraction_provider: Literal["deterministic", "sonar", "deepseek"] = "sonar"
    strict_free_tier: bool = False
    google_maps_server_api_key: str = ""
    google_maps_api_key: str = ""
    enable_google_places_discovery: bool = True
    pricing_google_place_details_enabled: bool = False
    google_places_base_url: str = "https://places.googleapis.com/v1"
    foursquare_api_key: str = ""
    foursquare_base_url: str = "https://places-api.foursquare.com"
    foursquare_api_version: str = "2025-06-17"
    enable_direct_source_fetch: bool = True
    source_fetch_timeout_seconds: float = 10.0
    source_fetch_max_bytes: int = 2_000_000
    source_fetch_max_redirects: int = 3
    third_party_freshness_months: int = 18
    competitor_research_deadline_seconds: float = 60.0

    # Competitor price source discovery and extraction. Raw Search finds
    # candidate pages; Sonar structures grounded results and handles the
    # bounded AI extraction fallback.
    perplexity_api_key: str = ""
    perplexity_search_base_url: str = "https://api.perplexity.ai"
    enable_perplexity_search: bool = True
    enable_perplexity_sonar: bool = True
    perplexity_sonar_model: str = "sonar"
    perplexity_sonar_max_tokens: int = 1600
    perplexity_search_country: str = "US"
    perplexity_search_context_size: str = "high"
    perplexity_max_results: int = 5
    perplexity_max_queries_per_competitor: int = 3
    perplexity_max_tokens_per_page: int = 2048
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    exa_api_key: str = ""
    exa_base_url: str = "https://api.exa.ai"
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev/v2"
    # Legacy settings remain accepted while old deployments roll forward.
    # The pricing workflow no longer calls these providers.
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

    # RAG embeddings — AWS Bedrock (Cohere Embed v4), same account as pulse-db.
    # Dimensions must match the model's actual output size — the pgvector column
    # (app/models/knowledge.py) is fixed at create time, so switching models later
    # requires a migration. The App Runner instance role (pulse-apprunner-instance)
    # holds bedrock:InvokeModel scoped to this exact model ARN; local dev uses
    # whatever AWS credentials are in the shell (aws sts get-caller-identity).
    bedrock_region: str = "us-east-1"
    bedrock_embedding_model: str = "cohere.embed-v4:0"
    embedding_dimensions: int = 1536

    @property
    def rag_configured(self) -> bool:
        return bool(self.bedrock_embedding_model)

    @property
    def effective_google_maps_api_key(self) -> str:
        """Never let a browser/referrer key become a production server credential."""
        if self.environment == "production":
            return self.google_maps_server_api_key
        return self.google_maps_server_api_key or self.google_maps_api_key

    @property
    def auth_configured(self) -> bool:
        """True once Supabase Auth is wired (URL is enough to verify via JWKS)."""
        return bool(self.supabase_url)

    # Email / SMS
    resend_api_key: str = ""
    resend_from_email: str = "hello@example.com"
    # Signs POST /api/automations/resend/webhook (Resend uses Svix — the secret
    # is the "whsec_..." value shown when you create the webhook endpoint).
    resend_webhook_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    # TCPA: no SMS before this local hour or at/after this one (24h, business's own timezone).
    sms_quiet_hours_start: int = 9
    sms_quiet_hours_end: int = 20
    # How often the automation dispatcher re-evaluates rules (Celery beat, seconds).
    automation_dispatch_interval_seconds: int = 900

    @property
    def resend_configured(self) -> bool:
        return bool(self.resend_api_key)

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)

    # ── Social presence (ported from Splay) ─────────────────────────────────
    # Buffer is the publishing rail for LinkedIn/X. One long-lived bearer token
    # plus opaque channel ids; there is no OAuth dance. Publishing is refused
    # outright unless the key and at least one channel id are present.
    buffer_api_key: str = ""
    buffer_api_url: str = "https://api.buffer.com"
    buffer_linkedin_profile_ids: str = ""  # comma-separated
    buffer_x_profile_ids: str = ""  # comma-separated
    buffer_profile_ids: str = ""  # fallback when the per-platform list is empty
    buffer_publish_mode: Literal["now", "queue"] = "now"

    # Buffer's own web pages, opened in a popup from the Social tab so an owner
    # can make an account and attach LinkedIn/X. Attaching a channel is not an
    # API operation — it completes a platform OAuth that Buffer, not Churnary,
    # is the registered partner for — so that step has to happen on Buffer.
    # login.buffer.com, not buffer.com/signup — the latter sits behind bot
    # protection and answers 403 to anything that isn't a full browser session.
    # The channels URL bounces through login and back, so one popup covers both
    # "sign in" and "attach an account".
    buffer_signup_url: str = "https://login.buffer.com/signup"
    buffer_channels_url: str = "https://publish.buffer.com/channels"

    @property
    def buffer_configured(self) -> bool:
        return bool(
            self.buffer_api_key
            and (
                self.buffer_linkedin_profile_ids
                or self.buffer_x_profile_ids
                or self.buffer_profile_ids
            )
        )

    # Seed values for a business's first brand kit, before they save their own.
    brand_name: str = ""
    brand_audience: str = ""
    brand_tone: str = "clear, specific, local"

    # Post imagery. TokenMart's media endpoints sit at the gateway *origin*,
    # while TOKENMART_BASE_URL above carries the /v1 suffix for chat calls.
    tokenmart_media_base_url: str = "https://model.service-inference.ai"
    tokenmart_image_model: str = "dola-seedream-5-0-pro-260628"
    tokenmart_image_size: str = "1280x720"
    tokenmart_video_model: str = "dreamina-seedance-2-0-260128"
    tokenmart_request_timeout_ms: int = 300000
    tokenmart_max_retries: int = 2

    # Public host for post media. Buffer fetches the image at publish time —
    # possibly weeks after scheduling — so the URL has to outlive the schedule.
    # This replaces Splay's Convex blob store.
    s3_media_bucket: str = ""
    s3_media_prefix: str = "social/"
    media_public_base_url: str = ""  # e.g. https://media.churnary.ai

    @property
    def media_host_configured(self) -> bool:
        return bool(self.s3_media_bucket and self.media_public_base_url)

    # Square OAuth app (Developer Dashboard → your app). Enables "Connect with Square".
    square_app_id: str = ""
    square_app_secret: str = ""
    square_environment: Literal["sandbox", "production"] = "sandbox"
    square_webhook_signature_key: str = ""
    # Must exactly match the notification URL registered with Square because it
    # is part of Square's HMAC signature input.
    square_webhook_url: str = ""

    # Stripe Connect platform (Dashboard → Settings → Connect). Enables
    # "Connect with Stripe"; token exchange authenticates with stripe_secret_key.
    stripe_connect_client_id: str = ""
    stripe_connect_webhook_secret: str = ""

    # Retention ingest defaults. Initial imports keep two years of payment
    # history; incremental pulls overlap to tolerate eventual consistency.
    payment_history_lookback_days: int = 730
    payment_sync_overlap_minutes: int = 10
    payment_sync_interval_seconds: int = 900

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_growth: str = ""
    stripe_price_pro: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> Settings:
        """Fail fast in production if critical secrets are missing or weak."""
        if not self.is_production:
            return self
        if self.auth_disabled:
            # A dev convenience that would be an open door in production.
            raise ValueError("AUTH_DISABLED must not be set in production")
        missing: list[str] = []
        if not self.fernet_key:
            missing.append("FERNET_KEY")
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if self.supabase_jwt_secret and len(self.supabase_jwt_secret) < 32:
            missing.append("SUPABASE_JWT_SECRET (must be >=32 chars or blank for JWKS)")
        if self.pricing_pipeline_v2_enabled:
            if not self.google_maps_server_api_key:
                missing.append("GOOGLE_MAPS_SERVER_API_KEY")
            if self.pricing_place_provider == "foursquare" and not self.foursquare_api_key:
                missing.append("FOURSQUARE_API_KEY")
            if self.pricing_search_provider == "perplexity" and not self.perplexity_api_key:
                missing.append("PERPLEXITY_API_KEY")
            if self.pricing_search_provider == "tavily" and not self.tavily_api_key:
                missing.append("TAVILY_API_KEY")
            if self.pricing_search_provider == "exa" and not self.exa_api_key:
                missing.append("EXA_API_KEY")
            if self.pricing_content_fallback == "tavily" and not self.tavily_api_key:
                missing.append("TAVILY_API_KEY")
            if self.pricing_content_fallback == "exa" and not self.exa_api_key:
                missing.append("EXA_API_KEY")
            if self.pricing_content_fallback == "firecrawl" and not self.firecrawl_api_key:
                missing.append("FIRECRAWL_API_KEY")
            if self.pricing_extraction_provider == "sonar" and not self.perplexity_api_key:
                missing.append("PERPLEXITY_API_KEY")
            if self.pricing_extraction_provider == "deepseek" and not (
                self.tokenmart_api_key or self.deepseek_api_key
            ):
                missing.append("TOKENMART_API_KEY or DEEPSEEK_API_KEY")
        if missing:
            missing = list(dict.fromkeys(missing))
            raise ValueError(
                f"Production requires these settings: {', '.join(missing)}"
            )
        return self

    # PostHog
    posthog_project_token: str = ""
    posthog_host: str = "https://us.i.posthog.com"
    posthog_disabled: bool = False

    # Platform-owned marketing visitor intelligence. This data is deliberately
    # separate from tenant customer data and only visible to platform admins.
    visitor_admin_emails: str = ""
    # RB2B's generic webhook cannot attach custom headers, so its opaque secret
    # is included as a query parameter in the URL configured in RB2B.
    rb2b_webhook_secret: str = ""
    rb2b_monthly_cost_usd: float = 0.0

    # Discord companion for RB2B/visitor intelligence. Alerts can be delivered
    # either by a channel webhook (least privilege) or by the bot user. Slash
    # commands use Discord's signed HTTP interactions endpoint, so the API does
    # not need a long-running Gateway/WebSocket worker.
    discord_application_id: str = ""
    discord_public_key: str = ""
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    discord_alert_channel_id: str = ""
    discord_webhook_url: str = ""
    discord_allowed_role_ids: str = ""
    discord_alert_min_intent_score: int = 25
    discord_include_email: bool = False

    @property
    def visitor_admin_email_set(self) -> set[str]:
        return {
            email.strip().casefold()
            for email in self.visitor_admin_emails.split(",")
            if email.strip()
        }

    @property
    def discord_allowed_role_id_set(self) -> set[str]:
        return {
            role_id.strip()
            for role_id in self.discord_allowed_role_ids.split(",")
            if role_id.strip()
        }

    @property
    def discord_alerts_configured(self) -> bool:
        return bool(
            self.discord_webhook_url
            or (self.discord_bot_token and self.discord_alert_channel_id)
        )

    @property
    def discord_commands_configured(self) -> bool:
        return bool(
            self.discord_application_id
            and self.discord_public_key
            and self.discord_guild_id
        )

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
