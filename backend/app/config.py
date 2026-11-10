from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"  # dev | test | prod
    database_url: str = "postgresql+psycopg://rs_app:rs_app@localhost:5432/reporting"
    jwt_secret: str = "dev-secret-change-me"
    platform_key: str = "dev-platform-key-change-me"  # derives the Fernet key for Slack webhooks
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    web_origin: str = "http://localhost:5173"
    public_web_url: str = "http://localhost:5173"
    cookie_secure: bool = False
    auth_rate_limit_per_min: int = 10
    bcrypt_rounds: int = 12

    email_backend: str = "console"  # console | smtp
    email_from: str = "Project Transparency <no-reply@example.com>"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_security: str = "starttls"  # starttls (port 587) | ssl (port 465, implicit TLS) | none (a local relay only)
    smtp_timeout: int = 20  # seconds, for connect and every command
    email_reply_to: str | None = None  # where replies go (default: nowhere, mail is sent from a no-reply address)

    # LLM for report drafting. ai_provider: auto (first configured key wins) | anthropic | openai | gemini | none.
    # A company can override provider/model/key in Settings; these are the platform defaults.
    ai_provider: str = "auto"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini-2024-07-18"  # pinned: upgrade = golden-set run + config change
    openai_base_url: str = "https://api.openai.com/v1"  # any OpenAI-compatible endpoint (Azure OpenAI, vLLM, ...)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash-001"
    ai_enabled: bool = True  # platform kill switch: false = built-in wording only, no model calls (re-read every 60 s by app.ai.policy)
    ai_max_input_tokens: int = 30000  # a model request above this (chars / 4) is refused with a "narrow the scope" message
    ai_monthly_token_budget: int = 0  # tokens per company per month; 0 = no alert. A warning is logged at 80 %
    google_client_id: str | None = None

    storage_dir: str = "./var/files"
    chromium_path: str | None = None
    worker_poll_seconds: int = 5
    job_backoff_seconds: int = 30

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_prod and (s.jwt_secret.startswith("dev-") or s.platform_key.startswith("dev-")):
        raise RuntimeError("JWT_SECRET and PLATFORM_KEY must be set in production")
    return s
