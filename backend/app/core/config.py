import os
from pathlib import Path

from dotenv import load_dotenv

_backend_root = Path(__file__).resolve().parents[2]
_env_file = _backend_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


class Settings:
    """Application configuration loaded from environment variables."""

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/mpai",
    )
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # pretty | json — json recommended behind aggregators / production
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "pretty").strip().lower()

    # Multi-tenant subdomain base (e.g. app.example.com → {slug}.app.example.com)
    TENANT_BASE_DOMAIN: str | None = os.getenv("TENANT_BASE_DOMAIN") or None

    # Shared secret for internal microservice → API tenant header overrides.
    # When unset, X-Tenant-Id spoofing is rejected for all non-superadmin callers.
    INTERNAL_SERVICE_API_KEY: str | None = (
        os.getenv("INTERNAL_SERVICE_API_KEY") or os.getenv("SERVICE_API_KEY") or None
    )

    # Rate limiting (slowapi)
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_DEFAULT: str = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")

    # Sentry (optional)
    SENTRY_DSN: str | None = os.getenv("SENTRY_DSN") or None
    SENTRY_TRACES_SAMPLE_RATE: float = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
    SENTRY_PROFILES_SAMPLE_RATE: float = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.0"))

    # OpenTelemetry (optional)
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None
    OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "mpai-api")

    # Stripe billing (optional until configured)
    # STRIPE_API_KEY is preferred; STRIPE_SECRET_KEY kept as alias for BC.
    STRIPE_API_KEY: str | None = (
        os.getenv("STRIPE_API_KEY") or os.getenv("STRIPE_SECRET_KEY") or None
    )
    STRIPE_SECRET_KEY: str | None = (
        os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_API_KEY") or None
    )
    STRIPE_WEBHOOK_SECRET: str | None = os.getenv("STRIPE_WEBHOOK_SECRET") or None
    PAYMENT_WEBHOOK_DEV_SECRET: str = os.getenv("PAYMENT_WEBHOOK_DEV_SECRET", "dev-payment-secret")
    STRIPE_PRICE_PRO: str | None = os.getenv("STRIPE_PRICE_PRO") or None
    STRIPE_PRICE_ENTERPRISE: str | None = os.getenv("STRIPE_PRICE_ENTERPRISE") or None
    STRIPE_PUBLISHABLE_KEY: str | None = os.getenv("STRIPE_PUBLISHABLE_KEY") or None
    # Optional Stripe Billing Meter event name (usage-based). Empty = local ledger only.
    STRIPE_METER_EVENT_NAME: str | None = os.getenv("STRIPE_METER_EVENT_NAME") or None
    STRIPE_METERING_ENABLED: bool = os.getenv("STRIPE_METERING_ENABLED", "false").lower() == "true"

    # AI safety
    AI_GUARDRAILS_ENABLED: bool = os.getenv("AI_GUARDRAILS_ENABLED", "true").lower() == "true"
    AI_MODERATION_ENABLED: bool = os.getenv("AI_MODERATION_ENABLED", "false").lower() == "true"

    # LLM providers
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o")
    OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL") or None
    OPENAI_FALLBACK_MODEL: str = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
    OPENAI_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    LLM_REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "20"))
    LOW_BALANCE_THRESHOLD_KZT: float = float(os.getenv("LOW_BALANCE_THRESHOLD_KZT", "2500"))

    # LLM Gateway credit tariff (integer minimal units per 1k tokens for unknown models).
    LLM_CREDIT_PROMPT_PER_1K: int = int(os.getenv("LLM_CREDIT_PROMPT_PER_1K", "10"))
    LLM_CREDIT_COMPLETION_PER_1K: int = int(os.getenv("LLM_CREDIT_COMPLETION_PER_1K", "30"))
    LLM_CREDIT_MULTIPLIER: float = float(os.getenv("LLM_CREDIT_MULTIPLIER", "1.0"))

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")
    OLLAMA_REQUEST_TIMEOUT_SECONDS: float = float(
        os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "60")
    )
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto")  # auto | openai | groq | openrouter | ollama

    # Groq (OpenAI-compatible, free-tier models)
    GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY") or None
    GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    GROQ_CHAT_MODEL: str = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-20b")

    # Secondary vendor the gateway switches to on 429 / 5xx / timeout / bad model.
    FALLBACK_LLM_PROVIDER: str = os.getenv("FALLBACK_LLM_PROVIDER", "groq")
    FALLBACK_LLM_MODEL: str = os.getenv("FALLBACK_LLM_MODEL", "openai/gpt-oss-20b")

    # OpenRouter (OpenAI-compatible; `:free` models for tests)
    OPENROUTER_API_KEY: str | None = os.getenv("OPENROUTER_API_KEY") or None
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    OPENROUTER_FREE_MODEL: str = os.getenv(
        "OPENROUTER_FREE_MODEL",
        "meta-llama/llama-3.2-3b-instruct:free",
    )

    # Image generation providers
    KLING_API_KEY: str | None = os.getenv("KLING_API_KEY")
    KLING_API_BASE_URL: str = os.getenv("KLING_API_BASE_URL", "https://api.klingai.com")
    KLING_IMAGE_MODEL: str = os.getenv("KLING_IMAGE_MODEL", "kling-v1")
    NANOBANANA_API_KEY: str | None = os.getenv("NANOBANANA_API_KEY")
    NANOBANANA_API_BASE_URL: str = os.getenv(
        "NANOBANANA_API_BASE_URL", "https://nanophoto.ai"
    )
    NANOBANANA_IMAGE_MODEL: str = os.getenv("NANOBANANA_IMAGE_MODEL", "nano-banana-pro")
    MEDIA_IMAGE_CREDIT_KLING: int = int(os.getenv("MEDIA_IMAGE_CREDIT_KLING", "500"))
    MEDIA_IMAGE_CREDIT_KLING_V2: int = int(os.getenv("MEDIA_IMAGE_CREDIT_KLING_V2", "1000"))
    MEDIA_IMAGE_CREDIT_NANOBANANA: int = int(os.getenv("MEDIA_IMAGE_CREDIT_NANOBANANA", "600"))
    MEDIA_IMAGE_CREDIT_NANOBANANA_4K: int = int(
        os.getenv("MEDIA_IMAGE_CREDIT_NANOBANANA_4K", "1200")
    )
    MEDIA_IMAGE_CREDIT_DEFAULT: int = int(os.getenv("MEDIA_IMAGE_CREDIT_DEFAULT", "500"))
    # Credits granted to OrganizationWallet on POST /auth/register (Free-tier starter).
    REGISTER_WALLET_STARTER_CREDITS: int = int(
        os.getenv("REGISTER_WALLET_STARTER_CREDITS", "0")
    )
    # Emails auto-promoted to is_superadmin on every seed / API start.
    PLATFORM_SUPERADMIN_EMAILS: list[str] = [
        email.strip().lower()
        for email in os.getenv(
            "PLATFORM_SUPERADMIN_EMAILS",
            "igor.mirkhanov@mail.ru,8saaask8@gmail.com",
        ).split(",")
        if email.strip()
    ]
    MEDIA_GENERATION_POLL_INTERVAL_SECONDS: float = float(
        os.getenv("MEDIA_GENERATION_POLL_INTERVAL_SECONDS", "0.05")
    )
    MEDIA_GENERATION_POLL_MAX_ATTEMPTS: int = int(
        os.getenv("MEDIA_GENERATION_POLL_MAX_ATTEMPTS", "3")
    )
    # Preferred alias for LLM Gateway factory (falls back to LLM_PROVIDER when unset).
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER") or os.getenv(
        "LLM_PROVIDER", "openai"
    )

    # Multi-vendor LLM Gateway credentials (OpenAI-compatible where noted).
    ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    GEMINI_API_KEY: str | None = (
        os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY") or None
    )
    DEEPSEEK_API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY") or None
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_CHAT_MODEL: str = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
    GLM_API_KEY: str | None = os.getenv("GLM_API_KEY") or os.getenv("ZHIPU_API_KEY") or None
    GLM_BASE_URL: str = os.getenv(
        "GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
    )
    GLM_CHAT_MODEL: str = os.getenv("GLM_CHAT_MODEL", "glm-5-turbo")
    QWEN_API_KEY: str | None = (
        os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or None
    )
    QWEN_BASE_URL: str = os.getenv(
        "QWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    QWEN_CHAT_MODEL: str = os.getenv("QWEN_CHAT_MODEL", "qwen-3.7-plus")

    # Vector store
    CHROMA_PERSIST_DIRECTORY: str = os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma")
    CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "knowledge_base_chunks")
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "auto")  # auto | openai | local

    # AI orchestration limits
    MAX_CHAT_HISTORY_MESSAGES: int = int(os.getenv("MAX_CHAT_HISTORY_MESSAGES", "10"))
    MAX_PROMPT_CHARS: int = int(os.getenv("MAX_PROMPT_CHARS", "12000"))
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "3"))

    # Knowledge base chunking
    KB_CHUNK_SIZE: int = int(os.getenv("KB_CHUNK_SIZE", "500"))
    KB_CHUNK_OVERLAP: int = int(os.getenv("KB_CHUNK_OVERLAP", "50"))

    # Optional Google Drive / Docs API key for folder listing & private exports
    GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY") or None
    GOOGLE_SYNC_TIMEOUT_SECONDS: float = float(os.getenv("GOOGLE_SYNC_TIMEOUT_SECONDS", "30"))
    GOOGLE_SYNC_MAX_FOLDER_FILES: int = int(os.getenv("GOOGLE_SYNC_MAX_FOLDER_FILES", "25"))

    # Telegram & webhooks
    WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")
    NGROK_TUNNEL_URL: str | None = os.getenv("NGROK_TUNNEL_URL") or None
    TELEGRAM_API_BASE: str = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org")
    # Omnichannel alias (same default); prefer TELEGRAM_API_BASE_URL when set.
    TELEGRAM_API_BASE_URL: str = os.getenv(
        "TELEGRAM_API_BASE_URL",
        os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org"),
    ).rstrip("/")
    TELEGRAM_DEFAULT_BOT_TOKEN: str | None = os.getenv("TELEGRAM_DEFAULT_BOT_TOKEN") or None
    GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID") or None
    GOOGLE_CLIENT_SECRET: str | None = os.getenv("GOOGLE_CLIENT_SECRET") or None

    WHATSAPP_SERVICE_URL: str = os.getenv("WHATSAPP_SERVICE_URL", "http://127.0.0.1:3001")
    WHATSAPP_SERVICE_WS_URL: str = os.getenv(
        "WHATSAPP_SERVICE_WS_URL",
        "ws://127.0.0.1:3001",
    )
    # WhatsApp Cloud API (Omnichannel connector — Meta Graph).
    WHATSAPP_API_VERSION: str = os.getenv("WHATSAPP_API_VERSION", "v18.0")
    WHATSAPP_BASE_URL: str = os.getenv(
        "WHATSAPP_BASE_URL", "https://graph.facebook.com"
    ).rstrip("/")
    WHATSAPP_VERIFY_TOKEN: str | None = os.getenv("WHATSAPP_VERIFY_TOKEN") or None
    WHATSAPP_ACCESS_TOKEN: str | None = os.getenv("WHATSAPP_ACCESS_TOKEN") or None
    WHATSAPP_PHONE_NUMBER_ID: str | None = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or None
    # Meta / Facebook app secret for X-Hub-Signature-256 on WhatsApp Cloud + Instagram.
    META_APP_SECRET: str | None = (
        os.getenv("META_APP_SECRET")
        or os.getenv("FACEBOOK_APP_SECRET")
        or os.getenv("WHATSAPP_APP_SECRET")
        or None
    )
    FACEBOOK_APP_SECRET: str | None = os.getenv("FACEBOOK_APP_SECRET") or None
    WHATSAPP_APP_SECRET: str | None = os.getenv("WHATSAPP_APP_SECRET") or None
    # Optional scrape token for Prometheus / deep health (falls back to INTERNAL_SERVICE_API_KEY).
    METRICS_SCRAPE_TOKEN: str | None = os.getenv("METRICS_SCRAPE_TOKEN") or None
    # AES-256-GCM primary key (32 bytes raw/hex/base64). Falls back to CREDENTIALS_ENCRYPTION_KEY.
    ENCRYPTION_KEY: str | None = os.getenv("ENCRYPTION_KEY") or os.getenv(
        "CREDENTIALS_ENCRYPTION_KEY"
    )
    CREDENTIALS_ENCRYPTION_KEY: str | None = os.getenv("CREDENTIALS_ENCRYPTION_KEY")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development"))

    # JWT access tokens (HS256). Must be set explicitly — never reuse encryption keys
    # (PRODUCTION_LAUNCH_CHECKLIST §2.2 / deploy.sh enforces distinctness).
    JWT_SECRET_KEY: str | None = os.getenv("JWT_SECRET_KEY") or None
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        # Short-lived access JWT; SPA renews via refresh token rotation.
        os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30"))

    # Dev-only: allow X-User-Id / demo user when Authorization is absent.
    # Always forced off in production regardless of this flag.
    ALLOW_SOFT_LAUNCH_AUTH: bool = (
        os.getenv("ALLOW_SOFT_LAUNCH_AUTH", "true").lower() == "true"
    )
    # Dev-only: allow OAuth stub that trusts client-supplied email (NEVER in prod).
    ALLOW_OAUTH_STUB: bool = os.getenv("ALLOW_OAUTH_STUB", "false").lower() == "true"
    # Dev-only reversible credential fallback (plain: prefix). Never enable in production/staging.
    ALLOW_PLAIN_CREDENTIAL_FALLBACK: bool = (
        os.getenv("ALLOW_PLAIN_CREDENTIAL_FALLBACK", "false").lower() == "true"
    )

    # Dedicated secret for legacy imp_* HMAC tokens (falls back to JWT_SECRET_KEY).
    IMPERSONATION_HMAC_SECRET: str | None = os.getenv("IMPERSONATION_HMAC_SECRET") or None

    # Public SPA URL (password-reset email stub links)
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # Host allow-list (comma-separated). Used to derive CORS origins in production.
    ALLOWED_HOSTS: list[str] = [
        host.strip()
        for host in os.getenv("ALLOWED_HOSTS", "").split(",")
        if host.strip()
    ]

    # Optional fastapi-users router mount (refresh/reset remain on /api/v1/auth)
    FASTAPI_USERS_ENABLED: bool = os.getenv("FASTAPI_USERS_ENABLED", "false").lower() == "true"

    # OAuth social stubs (Google / GitHub) — redirect URLs only until real client IDs set
    GOOGLE_OAUTH_CLIENT_ID: str | None = os.getenv("GOOGLE_OAUTH_CLIENT_ID") or None
    GOOGLE_OAUTH_CLIENT_SECRET: str | None = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or None
    GITHUB_OAUTH_CLIENT_ID: str | None = os.getenv("GITHUB_OAUTH_CLIENT_ID") or None
    GITHUB_OAUTH_CLIENT_SECRET: str | None = os.getenv("GITHUB_OAUTH_CLIENT_SECRET") or None

    # CORS — include common Next.js dev ports
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() in {"production", "prod"}

    @property
    def resolved_chat_model(self) -> str:
        """Map aliases like ``openrouter/free`` to a real vendor model id."""
        raw = (self.OPENAI_CHAT_MODEL or "").strip()
        provider = (self.LLM_PROVIDER or "").strip().lower()
        aliases = {"openrouter/free", "free", "openrouter-free"}
        if raw.lower() in aliases:
            if provider == "groq":
                return (self.GROQ_CHAT_MODEL or "openai/gpt-oss-20b").strip()
            return (self.OPENROUTER_FREE_MODEL or "meta-llama/llama-3.2-3b-instruct:free").strip()
        if provider == "groq":
            groq_model = (self.GROQ_CHAT_MODEL or "").strip()
            if groq_model and (
                not raw
                or raw.lower().startswith("openai/")
                or raw.lower().startswith("gpt-")
            ):
                return groq_model
        return raw or "gpt-4o-mini"

    @property
    def resolved_openai_base_url(self) -> str | None:
        explicit = (self.OPENAI_BASE_URL or "").strip() or None
        if explicit:
            return explicit
        provider = (self.LLM_PROVIDER or "").strip().lower()
        if provider == "openrouter":
            return (self.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1").rstrip("/")
        if provider == "groq":
            return (self.GROQ_BASE_URL or "https://api.groq.com/openai/v1").rstrip("/")
        return None

    @property
    def is_free_llm_route(self) -> bool:
        """True when the configured chat path is a free Groq / OpenRouter / local model."""
        provider = (self.LLM_PROVIDER or "").strip().lower()
        model = self.resolved_chat_model.lower()
        alias = (self.OPENAI_CHAT_MODEL or "").strip().lower()
        if provider in {"groq", "ollama"}:
            return True
        if model.endswith(":free") or alias in {"openrouter/free", "free", "openrouter-free"}:
            return True
        return False

    @property
    def cors_allow_origins(self) -> list[str]:
        """
        Strict CORS origin list.

        Always includes ``FRONTEND_URL``. In production, rejects ``*`` wildcards
        and synthesizes ``https://`` origins from ``ALLOWED_HOSTS`` when needed.
        """
        origins: list[str] = []
        frontend = (self.FRONTEND_URL or "").rstrip("/")
        if frontend:
            origins.append(frontend)

        for origin in self.CORS_ORIGINS:
            cleaned = origin.rstrip("/")
            if cleaned and cleaned not in origins:
                origins.append(cleaned)

        for host in self.ALLOWED_HOSTS:
            host_clean = host.strip().rstrip("/")
            if not host_clean or host_clean == "*":
                continue
            if host_clean.startswith("http://") or host_clean.startswith("https://"):
                candidate = host_clean
            else:
                candidate = f"https://{host_clean}"
            if candidate not in origins:
                origins.append(candidate)

        if self.is_production:
            origins = [o for o in origins if o != "*"]
            if not origins and frontend:
                origins = [frontend]

        return origins

    # Operator WebSocket auth (development mock token)
    OPERATOR_WS_TOKEN: str = os.getenv("OPERATOR_WS_TOKEN", "dev-operator-token")
    WS_HEARTBEAT_INTERVAL: int = int(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))

    # Redis & Celery task queue
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = os.getenv(
        "CELERY_BROKER_URL",
        "redis://localhost:6379/1",
    )
    CELERY_RESULT_BACKEND: str = os.getenv(
        "CELERY_RESULT_BACKEND",
        "redis://localhost:6379/2",
    )

    # SQLAlchemy async connection pool (see app.db.session)
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "50"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "10"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))

    # Flow Builder engine — hop limit + Redis session TTL.
    FLOW_MAX_EXECUTION_STEPS: int = int(os.getenv("FLOW_MAX_EXECUTION_STEPS", "50"))
    FLOW_SESSION_TTL_SECONDS: int = int(os.getenv("FLOW_SESSION_TTL_SECONDS", "86400"))
    CELERY_TASK_ALWAYS_EAGER: bool = (
        os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"
    )
    CELERY_INBOUND_QUEUE: str = os.getenv("CELERY_INBOUND_QUEUE", "inbound_messages")
    CELERY_CRM_QUEUE: str = os.getenv("CELERY_CRM_QUEUE", "crm_actions")
    CELERY_INBOUND_MAX_RETRIES: int = int(os.getenv("CELERY_INBOUND_MAX_RETRIES", "3"))
    CELERY_INBOUND_RETRY_BACKOFF: int = int(os.getenv("CELERY_INBOUND_RETRY_BACKOFF", "30"))
    # When true, deal mutations enqueue automation runs on crm_actions instead of
    # awaiting them inline (prod). Default false so local/unit paths stay in-session.
    CRM_AUTOMATIONS_USE_CELERY: bool = (
        os.getenv("CRM_AUTOMATIONS_USE_CELERY", "false").lower() == "true"
    )

    # LLM response cache (Redis exact-match, 24h default TTL)
    LLM_CACHE_ENABLED: bool = os.getenv("LLM_CACHE_ENABLED", "true").lower() == "true"
    LLM_CACHE_TTL_SECONDS: int = int(os.getenv("LLM_CACHE_TTL_SECONDS", str(24 * 60 * 60)))

    # Production vector store (optional dedicated Chroma server)
    CHROMA_SERVER_HOST: str | None = os.getenv("CHROMA_SERVER_HOST") or None
    CHROMA_SERVER_PORT: int = int(os.getenv("CHROMA_SERVER_PORT", "8000"))

    # Local file uploads (bot avatars, etc.)
    UPLOADS_DIR: str = os.getenv(
        "UPLOADS_DIR",
        str(_backend_root / "data" / "uploads"),
    )


settings = Settings()


def is_seeded_superadmin_email(email: str | None) -> bool:
    """True for platform-owner accounts listed in PLATFORM_SUPERADMIN_EMAILS."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return False
    return normalized in set(settings.PLATFORM_SUPERADMIN_EMAILS)


def resolve_webhook_base_url() -> str:
    """Prefer NGROK_TUNNEL_URL in development when a public tunnel is active."""
    if settings.NGROK_TUNNEL_URL:
        return settings.NGROK_TUNNEL_URL.rstrip("/")
    return settings.WEBHOOK_BASE_URL.rstrip("/")


def is_public_https_webhook_url(url: str) -> bool:
    """Telegram setWebhook only accepts a publicly reachable HTTPS URL."""
    from urllib.parse import urlparse
    import ipaddress

    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return "." in host
