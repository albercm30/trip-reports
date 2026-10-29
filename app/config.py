"""Settings read from environment variables (see .env.example)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv() -> None:
    """Load a local .env file for development. Real environment variables win."""
    p = Path(os.environ.get("ENV_FILE", ".env"))
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Settings:
    env: str = "development"
    app_name: str = "Trip Reports"
    app_name_es: str = "Informes de Viaje"
    app_url: str = "http://localhost:8000"
    secret_key: str = ""
    database_url: str = "sqlite:///./tripreports.db"

    # AI (Anthropic Claude API)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_fast_model: str = "claude-haiku-5-5"
    # Any OpenAI-compatible provider (default: Groq, which has a free tier)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"

    # Billing (Stripe)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_prices: dict = field(default_factory=dict)
    trial_days: int = 14

    # Storage for photos and logos
    storage: str = "local"  # local | db | s3
    upload_dir: str = "./uploads"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""

    # Email (optional; without it, links are shown on screen / logged)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    mail_from_name: str = ""
    brevo_api_key: str = ""
    cf_account_id: str = ""  # Cloudflare Workers AI (free 10,000 neurons a day): same gpt-oss-120b as overflow
    cf_api_token: str = ""  # Brevo's HTTP API: works where SMTP ports are blocked (Render's free tier)

    # Species name checks against the GBIF Backbone Taxonomy (CC BY 4.0)
    gbif_check: bool = True

    support_email: str = ""
    legal_name: str = ""
    legal_address: str = ""
    legal_id: str = ""
    show_prices: bool = False  # SHOW_PRICES=1 shows plan prices; hidden (blurred) during the pilot  # NIF/CIF, shown in the legal notice when set
    admin_emails: tuple = ()  # who can see /app/admin (pilot accounts)

    def name_for(self, lang: str) -> str:
        """The product name in a language (a real brand would use one name everywhere)."""
        return self.app_name_es if lang == "es" else self.app_name

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key or self.llm_api_key or (self.cf_account_id and self.cf_api_token))

    @property
    def ai_provider(self) -> str:
        if self.anthropic_api_key:
            return "anthropic"
        return "openai" if (self.llm_api_key or (self.cf_account_id and self.cf_api_token)) else ""

    @property
    def billing_enabled(self) -> bool:
        return bool(self.stripe_secret_key)

    @property
    def mail_enabled(self) -> bool:
        return bool((self.smtp_host or self.brevo_api_key) and self.mail_from)

    def is_admin(self, email: str | None) -> bool:
        return bool(email) and email.strip().lower() in self.admin_emails


def load_settings() -> Settings:
    _load_dotenv()
    env = _env("APP_ENV", "development")
    secret = _env("SECRET_KEY")
    if not secret:
        if env == "production":
            raise RuntimeError("SECRET_KEY must be set in production.")
        secret = "dev-" + secrets.token_hex(16)
    db = _env("DATABASE_URL", "sqlite:///./tripreports.db")
    # Render/Heroku style URLs -> SQLAlchemy psycopg 3 driver
    if db.startswith("postgres://"):
        db = "postgresql+psycopg://" + db[len("postgres://"):]
    elif db.startswith("postgresql://"):
        db = "postgresql+psycopg://" + db[len("postgresql://"):]
    prices = {
        ("starter", "month"): _env("STRIPE_PRICE_STARTER_MONTHLY"),
        ("starter", "year"): _env("STRIPE_PRICE_STARTER_YEARLY"),
        ("pro", "month"): _env("STRIPE_PRICE_PRO_MONTHLY"),
        ("pro", "year"): _env("STRIPE_PRICE_PRO_YEARLY"),
    }
    return Settings(
        env=env,
        app_name=_env("APP_NAME", "Trip Reports"),
        app_name_es=_env("APP_NAME_ES") or _env("APP_NAME_ES_DEFAULT", "") or (
            "Informes de Viaje" if not _env("APP_NAME") else _env("APP_NAME")),
        app_url=_env("APP_URL", "http://localhost:8000").rstrip("/"),
        secret_key=secret,
        database_url=db,
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        anthropic_fast_model=_env("ANTHROPIC_FAST_MODEL", "claude-haiku-5-5"),
        llm_api_key=_env("LLM_API_KEY"),
        llm_base_url=_env("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
        llm_model=_env("LLM_MODEL", "openai/gpt-oss-120b"),
        stripe_secret_key=_env("STRIPE_SECRET_KEY"),
        stripe_webhook_secret=_env("STRIPE_WEBHOOK_SECRET"),
        stripe_prices={k: v for k, v in prices.items() if v},
        trial_days=int(_env("TRIAL_DAYS", "14") or 14),
        storage=_env("STORAGE", "local"),
        upload_dir=_env("UPLOAD_DIR", "./uploads"),
        s3_bucket=_env("S3_BUCKET"),
        s3_region=_env("S3_REGION"),
        s3_endpoint_url=_env("S3_ENDPOINT_URL"),
        smtp_host=_env("SMTP_HOST"),
        smtp_port=int(_env("SMTP_PORT", "587") or 587),
        smtp_user=_env("SMTP_USER"),
        smtp_password=_env("SMTP_PASSWORD"),
        mail_from=_env("MAIL_FROM"),
        mail_from_name=_env("MAIL_FROM_NAME"),
        brevo_api_key=_env("BREVO_API_KEY"),
        cf_account_id=_env("CF_ACCOUNT_ID"),
        cf_api_token=_env("CF_API_TOKEN"),
        gbif_check=_bool("GBIF_CHECK", True),
        support_email=_env("SUPPORT_EMAIL"),
        legal_name=_env("LEGAL_NAME"),
        legal_address=_env("LEGAL_ADDRESS"),
        legal_id=_env("LEGAL_ID"),
        show_prices=_bool("SHOW_PRICES", False),
        admin_emails=tuple(e.strip().lower() for e in _env("ADMIN_EMAILS").split(",") if e.strip()),
    )


settings = load_settings()
