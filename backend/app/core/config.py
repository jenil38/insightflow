"""
Centralized application configuration.

All environment-driven settings live here. Nothing else in the codebase
should call os.getenv() directly for app config - import `settings` instead.
This gives us one validated source of truth and fails fast on boot if
something required is missing/misconfigured, instead of failing later
inside a random request handler.
"""

import os
import secrets
import warnings
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    APP_NAME: str = "InsightFlow AI API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development | staging | test | production
    DEBUG: bool = True

    # --- Database ---
    DATABASE_URL: str = "sqlite:///./insightflow.db"

    # --- Auth / JWT ---
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    RESET_TOKEN_EXPIRE_HOURS: int = 1

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Uploads ---
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    # --- Rate limiting ---
    # The default limit applies to every route; analytics-heavy screens fire
    # several requests per page view, so it is deliberately generous.
    RATE_LIMIT_DEFAULT: str = "300/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # --- Per-user limits ---
    MAX_DATASETS_PER_USER: int = 50
    MAX_STORAGE_PER_USER_MB: int = 500
    MAX_TRAINING_JOBS_PER_HOUR: int = 10
    MAX_REPORTS_PER_HOUR: int = 20
    MAX_COPILOT_MESSAGES_PER_HOUR: int = 60

    # --- Data processing safeguards ---
    # Row-level preview: hard ceiling on page size, so a client can never ask
    # the server to serialize an entire dataset into one JSON response.
    PREVIEW_MAX_PAGE_SIZE: int = 200
    # Profiling/analytics sample ceiling. Datasets above this are analysed on a
    # deterministic random sample, and the response says so explicitly
    # (`sampled: true`) rather than quietly reporting partial numbers.
    PROFILE_SAMPLE_ROWS: int = 200_000
    # Training sample ceiling - keeps one /train request from pinning a worker
    # for many minutes on a very large upload.
    MAX_TRAIN_ROWS: int = 100_000
    # Correlation matrices are O(ncols^2), so cap the columns considered.
    MAX_CORRELATION_COLUMNS: int = 25

    # --- AI Copilot (Groq) ---
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_TIMEOUT_SECONDS: int = 45
    # How many sample rows reach the LLM. Deliberately small: the Copilot is
    # grounded on computed statistics, not on raw record dumps.
    COPILOT_SAMPLE_ROWS: int = 5
    COPILOT_HISTORY_TURNS: int = 8

    # --- Email (logs instead of sending unless SMTP_HOST is set) ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "no-reply@insightflow.ai"
    FRONTEND_URL: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT.lower() == "test"

    @property
    def copilot_enabled(self) -> bool:
        """Whether the AI Copilot can actually reach an LLM. The UI reads this
        via /health so it can show an honest 'not configured' state instead of
        offering a chat box that always errors."""
        return bool(self.GROQ_API_KEY)

    @property
    def model_dir(self) -> str:
        return os.path.join(self.UPLOAD_DIR, "models")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    if not settings.JWT_SECRET:
        if settings.is_production:
            raise RuntimeError(
                "JWT_SECRET must be set explicitly in production. "
                "Set it via environment variable or .env file."
            )
        # Dev-only fallback so the app still boots locally without a .env file.
        settings.JWT_SECRET = secrets.token_urlsafe(32)
        if not settings.is_testing:
            warnings.warn(
                "JWT_SECRET not set - using an ephemeral generated secret. "
                "Tokens will be invalidated on restart. Set JWT_SECRET in .env for real use.",
                stacklevel=2,
            )

    if settings.is_production and "sqlite" in settings.DATABASE_URL:
        warnings.warn(
            "Running in production with SQLite. Postgres is strongly recommended "
            "(see DATABASE_URL) for concurrency and durability.",
            stacklevel=2,
        )

    return settings


settings = get_settings()
